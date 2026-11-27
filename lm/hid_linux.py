"""Linux HID via sysfs, hidraw and evdev."""
import errno
import os
import select
import sys
import threading
import time
from collections import deque
from contextlib import suppress
from math import ceil
from pathlib import Path

from .hid_adapter import CAPS, MAX_LENGTH, MAX_QUEUE, HidDev, HidProblem

if sys.platform.startswith("linux"):
    import fcntl

_OPEN_FLAGS = os.O_NONBLOCK | os.O_CLOEXEC if sys.platform.startswith("linux") else 0
_REMOVED = (errno.ENOENT, errno.ENODEV, errno.ENXIO)
_FEATURE_SET, _FEATURE_GET = 0x06, 0x07
_ZERO_PREFIX_BUSES = (0x03, 0x18)  # BUS_USB and BUS_I2C.
EVIOCGRAB = (1 << 30) | (4 << 16) | (ord("E") << 8) | 0x90


def error_category(code, *, opened=False):
    if code in _REMOVED:
        return "disconnected" if opened else "not-found"
    return {errno.EACCES: "permission", errno.EPERM: "permission",
            errno.EBUSY: "busy"}.get(code, "io")


def _short_items(descriptor):
    offset = 0
    while offset < len(descriptor):
        prefix = descriptor[offset]
        offset += 1
        if prefix == 0xFE and offset + 2 > len(descriptor):
            return
        if prefix == 0xFE:
            offset += 2 + descriptor[offset]
            continue
        size = (0, 1, 2, 4)[prefix & 3]
        end = offset + size
        if end > len(descriptor):
            return
        yield prefix & 0xFC, size, int.from_bytes(descriptor[offset:end], "little")
        offset = end


def descriptor_info(descriptor):
    page = primary_page = primary_usage = -1
    pages = []
    usage = None
    collection = numbered = False
    for tag, size, value in _short_items(descriptor):
        if tag == 0x84 and size == 1:
            numbered = True
        if collection:
            continue
        if tag == 0x04:
            page = value
        if tag == 0xA4:
            pages.append(page)
        if tag == 0xB4 and pages:
            page = pages.pop()
        if tag == 0x08 and usage is None:
            usage = (value >> 16, value & 0xFFFF) if size == 4 else (page, value)
        if tag == 0xA0:
            collection = True
            primary_page, primary_usage = usage if usage is not None else (page, -1)
        if tag & 0x0C == 0:
            usage = None  # Local items apply only to the next main item.
    return primary_page, primary_usage, numbered


def _hex(value):
    try:
        number = int(value, 16)
    except ValueError:
        return -1
    return number if 0 <= number <= 0xFFFFFFFF else -1


def parse_uevent(text):
    props = dict(line.split("=", 1) for line in text.split("\n") if "=" in line)
    parts = props.get("HID_ID", "").split(":")
    bus, vendor, product = map(_hex, parts) if len(parts) == 3 else (-1, -1, -1)
    return bus, vendor, product, props.get("HID_NAME", ""), props.get("HID_UNIQ", "")


def _interface(device):
    for directory in device.parents:
        with suppress(OSError):
            return _hex((directory / "bInterfaceNumber").read_text().strip())
    return -1


def _read_optional(path):
    try:
        return path.read_bytes()
    except OSError:
        return b""


def _device_uevent(device):
    return parse_uevent(_read_optional(device / "uevent").decode("utf-8", errors="replace"))


def frame_report(ident, data):
    return bytes((ident,)) + data


def input_report(numbered, data):
    return (data[0], data[1:]) if numbered else (0, data)


def feature_payload(ident, data, length, *, zero_prefixed=False):
    # USB and I2C retain a synthetic ID byte for unnumbered replies.
    if (ident or zero_prefixed) and data and data[0] == ident:
        data = data[1:]
    return data[:length]


def feature_request(command, size):
    # asm-generic _IOWR, shared by Linux amd64 and arm64.
    return (3 << 30) | (size << 16) | (ord("H") << 8) | command


def _children(path, prefix):
    try:
        return sorted(child for child in path.iterdir() if child.name.startswith(prefix))
    except FileNotFoundError:
        return []


def _event_paths(device, dev_root):
    for group in _children(device / "input", "input"):
        yield from (dev_root / "input" / event.name for event in _children(group, "event"))


def _close_fd(fd):
    with suppress(OSError):
        os.close(fd)


def _release_grabs(fds):
    for fd in reversed(fds):
        with suppress(OSError):
            fcntl.ioctl(fd, EVIOCGRAB, 0)
        _close_fd(fd)
    fds.clear()


def _open_raw(path):
    try:
        return os.open(path, os.O_RDWR | _OPEN_FLAGS), False
    except OSError as error:
        if error.errno != errno.EACCES:
            raise
    return os.open(path, os.O_RDONLY | _OPEN_FLAGS), True


class _Device:
    def __init__(self, fd, path, numbered, readonly, zero_prefixed=False):
        self.fd = fd
        self.path = path
        self.numbered = numbered
        self.readonly = readonly
        self.zero_prefixed = zero_prefixed
        self.connected = True
        self.queue = deque(maxlen=MAX_QUEUE)
        self.grabs = []


class LinuxHid:
    def __init__(self, sys_root="/sys/class/hidraw", dev_root="/dev"):
        self.sys_root = Path(sys_root)
        self.dev_root = Path(dev_root)
        self.devices = {}
        self.open_ids = set()
        self.lock = threading.Lock()
        self.wake_lock = threading.Lock()
        self.stopping = threading.Event()
        self.wake = None

    def invoke(self, op, *args):
        ops = {"enumerate": self.enumerate, "open": self.open, "read": self.read,
               "write": self.write, "feature-get": self.feature_get,
               "feature-set": self.feature_set, "grab": self.grab, "wait": self.wait,
               "close": self.close, "supports": CAPS.__contains__}
        with self.lock:
            if self.stopping.is_set():
                raise HidProblem("", "disconnected")
            return ops[op](*args)

    def _scan(self, ident=""):
        try:
            nodes = _children(self.sys_root, "hidraw")
        except OSError as error:
            raise HidProblem(ident, error_category(error.errno)) from None
        for node in nodes:
            try:
                device = (node / "device").resolve(strict=True)
            except OSError as error:
                if error.errno in _REMOVED:
                    continue
                raise HidProblem(ident, error_category(error.errno)) from None
            yield "linux:" + device.name.lower(), node, device

    def enumerate(self):
        rows = []
        for ident, _, device in self._scan():
            _, vendor, product, name, serial = _device_uevent(device)
            page, usage, _ = descriptor_info(_read_optional(device / "report_descriptor"))
            rows.append((ident, vendor, product, page, usage, _interface(device), name, serial))
        return tuple(sorted(rows, key=lambda row: row[0]))

    def open(self, ident):
        if ident in self.open_ids:
            raise HidProblem(ident, "busy")
        match = next((entry for entry in self._scan(ident) if entry[0] == ident), None)
        if match is None:
            raise HidProblem(ident, "not-found")
        _, node, device = match
        bus, *_ = _device_uevent(device)
        try:
            _, _, numbered = descriptor_info((device / "report_descriptor").read_bytes())
            fd, readonly = _open_raw(self.dev_root / node.name)
        except OSError as error:
            raise HidProblem(ident, error_category(error.errno)) from None
        try:
            if (node / "device").resolve(strict=True) != device:
                raise HidProblem(ident, "not-found")
        except BaseException as error:
            _close_fd(fd)
            if isinstance(error, OSError):
                raise HidProblem(ident, error_category(error.errno)) from None
            raise
        handle = HidDev(ident)
        zero_prefixed = bus in _ZERO_PREFIX_BUSES
        self.devices[handle] = _Device(fd, device, numbered, readonly, zero_prefixed)
        self.open_ids.add(ident)
        return handle

    def _state(self, handle, *, drain=False, writable=False):
        state = self.devices.get(handle)
        if state is None or (not drain and not state.connected):
            raise HidProblem(handle.id, "disconnected")
        if writable and state.readonly:
            raise HidProblem(handle.id, "permission")
        return state

    def _drain(self, handle, state):
        while state.connected and not self.stopping.is_set():
            try:
                data = os.read(state.fd, MAX_LENGTH + 1)
            except BlockingIOError:
                return
            except OSError as error:
                if error.errno in (*_REMOVED, errno.EIO):
                    state.connected = False
                    return
                raise HidProblem(handle.id, error_category(error.errno, opened=True)) from None
            if not data:
                state.connected = False
                return
            state.queue.append(input_report(state.numbered, data))

    def read(self, handle):
        state = self._state(handle, drain=True)
        self._drain(handle, state)
        if state.queue:
            return state.queue.popleft()
        self._state(handle)
        return None

    def _io_error(self, handle, state, error):
        category = error_category(error.errno, opened=True)
        if category == "disconnected":
            state.connected = False
        raise HidProblem(handle.id, category) from None

    def write(self, handle, ident, data):
        state = self._state(handle, writable=True)
        report = frame_report(ident, data)
        try:
            count = os.write(state.fd, report)
        except OSError as error:
            self._io_error(handle, state, error)
        if count != len(report):
            raise HidProblem(handle.id, "io")

    def feature_set(self, handle, ident, data):
        state = self._state(handle, writable=True)
        self._feature(handle, state, _FEATURE_SET, bytearray(frame_report(ident, data)))

    def feature_get(self, handle, ident, length):
        data = bytearray(length + 1)
        data[0] = ident
        state = self._state(handle, writable=True)
        size = self._feature(handle, state, _FEATURE_GET, data)
        if not 0 <= size <= len(data):
            raise HidProblem(handle.id, "io")
        return feature_payload(ident, bytes(data[:size]), length, zero_prefixed=state.zero_prefixed)

    def _feature(self, handle, state, command, data):
        try:
            return fcntl.ioctl(state.fd, feature_request(command, len(data)), data)
        except OSError as error:
            self._io_error(handle, state, error)

    def grab(self, handle, on):
        state = self._state(handle, drain=not on)
        if not on:
            _release_grabs(state.grabs)
            return
        if state.grabs:
            return
        try:
            self._grab_events(state)
        except OSError as error:
            _release_grabs(state.grabs)
            raise HidProblem(handle.id, error_category(error.errno, opened=True)) from None
        if not state.grabs:
            raise HidProblem(handle.id, "unsupported")

    def _grab_events(self, state):
        for path in _event_paths(state.path, self.dev_root):
            fd = os.open(path, os.O_RDONLY | _OPEN_FLAGS)
            try:
                fcntl.ioctl(fd, EVIOCGRAB, 1)
            except OSError:
                _close_fd(fd)
                raise
            state.grabs.append(fd)

    def _poll(self, entries, timeout):
        with self.wake_lock:
            if self.stopping.is_set():
                return {}
            if self.wake is None:
                self.wake = os.pipe2(_OPEN_FLAGS)
        poller = select.poll()
        poller.register(self.wake[0], select.POLLIN)
        for _, state in entries:
            if state.connected:
                poller.register(state.fd, select.POLLIN)
        return dict(poller.poll(timeout))

    def wait(self, handles, timeout):
        entries = [(handle, self._state(handle, drain=True)) for handle in handles]
        deadline = time.monotonic() + timeout / 1000
        while not self.stopping.is_set():
            ready = any(state.queue or not state.connected for _, state in entries)
            remaining = max(0, deadline - time.monotonic())
            try:
                events = self._poll(entries, 0 if ready else ceil(remaining * 1000))
            except OSError as error:
                raise HidProblem("", error_category(error.errno, opened=True)) from None
            for handle, state in entries:
                self._poll_device(handle, state, events.get(state.fd, 0))
            indices = tuple(i for i, (_, state) in enumerate(entries)
                            if state.queue or not state.connected)
            if indices or time.monotonic() >= deadline:
                return indices
        return ()

    def _poll_device(self, handle, state, event):
        if event & (select.POLLIN | select.POLLHUP | select.POLLERR):
            self._drain(handle, state)
        if event & (select.POLLHUP | select.POLLERR | select.POLLNVAL):
            state.connected = False

    def close(self, handle):
        state = self.devices.pop(handle, None)
        if state is None:
            return
        self.open_ids.remove(handle.id)
        _release_grabs(state.grabs)
        _close_fd(state.fd)

    def shutdown(self):
        with self.wake_lock:
            if not self.stopping.is_set() and self.wake is not None:
                self.stopping.set()
                os.write(self.wake[1], b"\0")
            self.stopping.set()
        with self.lock:
            for handle in tuple(self.devices):
                self.close(handle)
            if self.wake is not None:
                for fd in self.wake:
                    _close_fd(fd)
                self.wake = None
