"""macOS HID via IOKit, with callbacks delivered on the caller's run loop."""
import ctypes as C
import threading
import time
from collections import deque
from contextlib import contextmanager

from .hid_adapter import CAPS, MAX_LENGTH, MAX_QUEUE, HidDev, HidProblem

_UTF8 = 0x08000100
_NUMBER_SINT64 = 4
_NOT_PERMITTED = 0xE00002E2
_EXCLUSIVE_ACCESS = 0xE00002C5
_REMOVED_CODES = frozenset((0xE00002C0, 0xE00002D7, 0xE00002D9))
_SEIZE = 1
_OUTPUT, _FEATURE = 1, 2
_LISTEN_EVENT = 1
_LOOP_FINISHED = 1
_WAIT_SLICE = 0.05
_prompted = False
_prompt_lock = threading.Lock()

_P = C.c_void_p
_INDEX = C.c_long
_U32 = C.c_uint32
_STATUS = C.c_int32
_INPUT_CB = C.CFUNCTYPE(None, _P, _STATUS, _P, C.c_int, _U32,
                        C.POINTER(C.c_uint8), _INDEX)
_REMOVAL_CB = C.CFUNCTYPE(None, _P, _STATUS, _P)


def device_id(registry_id):
    return f"darwin:{registry_id:x}"


def error_category(status, *, opened=False):
    code = status & 0xFFFFFFFF
    if opened and code in _REMOVED_CODES:
        return "disconnected"
    return {_NOT_PERMITTED: "permission", _EXCLUSIVE_ACCESS: "busy"}.get(code, "io")


def frame_report(ident, data):
    return bytes((ident,)) + data if ident else data


def input_payload(ident, data):
    return data[1:] if ident else data


def feature_payload(ident, data):
    return data[1:] if ident and data and data[0] == ident else data


def _bind(lib, signatures):
    for name, result, *args in signatures:
        function = getattr(lib, name)
        function.restype = result
        function.argtypes = args


class _DarwinAPI:
    def __init__(self):
        frameworks = "/System/Library/Frameworks"
        self.cf = C.CDLL(f"{frameworks}/CoreFoundation.framework/CoreFoundation")
        self.hid = C.CDLL(f"{frameworks}/IOKit.framework/IOKit")
        _bind(self.cf, (
            ("CFRelease", None, _P),
            ("CFRetain", _P, _P),
            ("CFSetGetCount", _INDEX, _P),
            ("CFSetGetValues", None, _P, _P),
            ("CFGetTypeID", C.c_ulong, _P),
            ("CFNumberGetTypeID", C.c_ulong),
            ("CFNumberGetValue", C.c_bool, _P, _INDEX, _P),
            ("CFStringGetTypeID", C.c_ulong),
            ("CFStringCreateWithCString", _P, _P, C.c_char_p, _U32),
            ("CFStringGetLength", _INDEX, _P),
            ("CFStringGetMaximumSizeForEncoding", _INDEX, _INDEX, _U32),
            ("CFStringGetCString", C.c_bool, _P, _P, _INDEX, _U32),
            ("CFRunLoopGetCurrent", _P),
            ("CFRunLoopRunInMode", _STATUS, _P, C.c_double, C.c_bool),
        ))
        _bind(self.hid, (
            ("IOHIDManagerCreate", _P, _P, _U32),
            ("IOHIDManagerSetDeviceMatching", None, _P, _P),
            ("IOHIDManagerCopyDevices", _P, _P),
            ("IOHIDDeviceGetService", _U32, _P),
            ("IORegistryEntryGetRegistryEntryID", _STATUS, _U32, C.POINTER(C.c_uint64)),
            ("IOHIDDeviceCreate", _P, _P, _U32),
            ("IOHIDDeviceGetProperty", _P, _P, _P),
            ("IOHIDDeviceOpen", _STATUS, _P, _U32),
            ("IOHIDDeviceClose", _STATUS, _P, _U32),
            ("IOHIDDeviceRegisterInputReportCallback", None, _P, _P, _INDEX, _INPUT_CB, _P),
            ("IOHIDDeviceRegisterRemovalCallback", None, _P, _REMOVAL_CB, _P),
            ("IOHIDDeviceScheduleWithRunLoop", None, _P, _P, _P),
            ("IOHIDDeviceUnscheduleFromRunLoop", None, _P, _P, _P),
            ("IOHIDDeviceSetReport", _STATUS, _P, C.c_int, _INDEX, _P, _INDEX),
            ("IOHIDDeviceGetReport", _STATUS, _P, C.c_int, _INDEX, _P, C.POINTER(_INDEX)),
        ))
        self.request_access = getattr(self.hid, "IOHIDRequestAccess", None)
        if self.request_access is not None:
            self.request_access.argtypes = (C.c_int,)
            self.request_access.restype = C.c_bool
        self.mode = _P.in_dll(self.cf, "kCFRunLoopDefaultMode")

    @contextmanager
    def scan(self, device):
        manager = self.hid.IOHIDManagerCreate(None, 0)
        if not manager:
            raise HidProblem(device, "io")
        try:
            self.hid.IOHIDManagerSetDeviceMatching(manager, None)
            matches = self.hid.IOHIDManagerCopyDevices(manager)
            if not matches:
                yield ()
                return
            try:
                refs = (_P * self.cf.CFSetGetCount(matches))()
                if refs:
                    self.cf.CFSetGetValues(matches, refs)
                yield refs
            finally:
                self.cf.CFRelease(matches)
        finally:
            self.cf.CFRelease(manager)

    def identity(self, ref):
        service = self.hid.IOHIDDeviceGetService(ref)
        registry = C.c_uint64()
        if service and self.hid.IORegistryEntryGetRegistryEntryID(service, C.byref(registry)) == 0:
            return device_id(registry.value), service
        return None, 0

    def property(self, ref, key):
        name = self.cf.CFStringCreateWithCString(None, key, _UTF8)
        if not name:
            return None
        try:
            return self.hid.IOHIDDeviceGetProperty(ref, name)
        finally:
            self.cf.CFRelease(name)

    def number(self, ref, key):
        value = self.property(ref, key)
        number = C.c_int64()
        if (value and self.cf.CFGetTypeID(value) == self.cf.CFNumberGetTypeID()
                and self.cf.CFNumberGetValue(value, _NUMBER_SINT64, C.byref(number))):
            return number.value
        return -1

    def string(self, ref, key):
        value = self.property(ref, key)
        if not value or self.cf.CFGetTypeID(value) != self.cf.CFStringGetTypeID():
            return ""
        size = self.cf.CFStringGetMaximumSizeForEncoding(self.cf.CFStringGetLength(value), _UTF8)
        if size < 0:
            return ""
        buffer = C.create_string_buffer(size + 1)
        if self.cf.CFStringGetCString(value, buffer, len(buffer), _UTF8):
            return buffer.value.decode("utf-8")
        return ""

    def pump(self, seconds, *, stop_after_source):
        return self.cf.CFRunLoopRunInMode(self.mode, seconds, stop_after_source)


def _prompt_for_access(request_access, status):
    global _prompted
    if status & 0xFFFFFFFF != _NOT_PERMITTED:
        return
    with _prompt_lock:
        if _prompted:
            return
        _prompted = True
        if request_access is not None:
            request_access(_LISTEN_EVENT)


class _Device:
    def __init__(self, api, ref):
        self.api = api
        self.ref = ref
        self.loop = api.cf.CFRunLoopGetCurrent()
        self.options = None
        self.connected = True
        self.queue = deque(maxlen=MAX_QUEUE)
        size = max(MAX_LENGTH + 1, api.number(ref, b"MaxInputReportSize"))
        self.buffer = (C.c_uint8 * size)()
        self.input_callback = _INPUT_CB(self._input)
        self.removal_callback = _REMOVAL_CB(self._removed)

    def _input(self, _context, status, _sender, _type, ident, report, length):
        if self.connected and status == 0 and 0 <= length <= len(self.buffer):
            self.queue.append((ident, input_payload(ident, C.string_at(report, length))))

    def _removed(self, _context, _status, _sender):
        self.connected = False

    def start(self, options):
        hid = self.api.hid
        status = hid.IOHIDDeviceOpen(self.ref, options)
        if status:
            _prompt_for_access(self.api.request_access, status)
            return status
        self.options = options
        hid.IOHIDDeviceRegisterInputReportCallback(
            self.ref, self.buffer, len(self.buffer), self.input_callback, None)
        hid.IOHIDDeviceRegisterRemovalCallback(self.ref, self.removal_callback, None)
        hid.IOHIDDeviceScheduleWithRunLoop(self.ref, self.loop, self.api.mode)
        return 0

    def stop(self):
        if self.options is None:
            return
        hid = self.api.hid
        hid.IOHIDDeviceUnscheduleFromRunLoop(self.ref, self.loop, self.api.mode)
        hid.IOHIDDeviceRegisterInputReportCallback(
            self.ref, self.buffer, len(self.buffer), _INPUT_CB(), None)
        hid.IOHIDDeviceRegisterRemovalCallback(self.ref, _REMOVAL_CB(), None)
        hid.IOHIDDeviceClose(self.ref, self.options)
        self.options = None

    def check_io(self, handle, status):
        if not status:
            return
        category = error_category(status, opened=True)
        if category == "disconnected":
            self.connected = False
        raise HidProblem(handle.id, category)


class DarwinHid:
    def __init__(self):
        self.api = _DarwinAPI()
        self.devices = {}
        self.open_ids = set()
        # The Python target can request shutdown from the main thread on SIGINT.
        self.lock = threading.Lock()
        self.stopping = threading.Event()

    def invoke(self, op, *args):
        ops = {"enumerate": self.enumerate, "open": self.open, "read": self.read,
               "write": self.write, "feature-get": self.feature_get,
               "feature-set": self.feature_set, "grab": self.grab, "wait": self.wait,
               "close": self.close, "supports": CAPS.__contains__}
        with self.lock:
            if self.stopping.is_set():
                raise HidProblem("", "disconnected")
            return ops[op](*args)

    def enumerate(self):
        rows = []
        keys = (b"VendorID", b"ProductID", b"PrimaryUsagePage", b"PrimaryUsage")
        with self.api.scan("") as refs:
            for ref in refs:
                ident, _ = self.api.identity(ref)
                if ident is None:
                    continue
                rows.append((ident, *(self.api.number(ref, key) for key in keys), -1,
                             self.api.string(ref, b"Product"),
                             self.api.string(ref, b"SerialNumber")))
        return tuple(sorted(rows, key=lambda row: row[0]))

    def _find(self, ident):
        with self.api.scan(ident) as refs:
            for ref in refs:
                device, service = self.api.identity(ref)
                if device != ident:
                    continue
                opened = self.api.hid.IOHIDDeviceCreate(None, service)
                if not opened:
                    raise HidProblem(ident, "io")
                return opened
        raise HidProblem(ident, "not-found")

    def open(self, ident):
        if ident in self.open_ids:
            raise HidProblem(ident, "busy")
        ref = self._find(ident)
        try:
            state = _Device(self.api, ref)
            status = state.start(0)
            if status:
                raise HidProblem(ident, error_category(status))
        except (HidProblem, MemoryError, OverflowError) as error:
            self.api.cf.CFRelease(ref)
            if isinstance(error, HidProblem):
                raise
            raise HidProblem(ident, "io") from None
        handle = HidDev(ident)
        self.api.cf.CFRetain(state.loop)
        self.devices[handle] = state
        self.open_ids.add(ident)
        return handle

    def _state(self, handle, *, drain=False):
        state = self.devices.get(handle)
        if state is None or (not drain and not state.connected):
            raise HidProblem(handle.id, "disconnected")
        return state

    def read(self, handle):
        self.api.pump(0, stop_after_source=False)
        state = self._state(handle, drain=True)
        if state.queue:
            return state.queue.popleft()
        self._state(handle)
        return None

    def _send(self, handle, kind, ident, data):
        state = self._state(handle)
        report = frame_report(ident, data)
        status = self.api.hid.IOHIDDeviceSetReport(state.ref, kind, ident, report, len(report))
        state.check_io(handle, status)

    def write(self, handle, ident, data):
        self._send(handle, _OUTPUT, ident, data)

    def feature_set(self, handle, ident, data):
        self._send(handle, _FEATURE, ident, data)

    def feature_get(self, handle, ident, length):
        state = self._state(handle)
        buffer = C.create_string_buffer(length + bool(ident))
        actual = _INDEX(len(buffer))
        status = self.api.hid.IOHIDDeviceGetReport(
            state.ref, _FEATURE, ident, buffer, C.byref(actual))
        state.check_io(handle, status)
        if not 0 <= actual.value <= len(buffer):
            raise HidProblem(handle.id, "io")
        return feature_payload(ident, buffer.raw[:actual.value])[:length]

    def grab(self, handle, on):
        state = self._state(handle)
        previous, options = state.options, _SEIZE if on else 0
        if previous == options:
            return
        state.stop()
        status = state.start(options)
        if not status:
            return
        if state.start(previous):
            state.connected = False
        raise HidProblem(handle.id, error_category(status))

    def wait(self, handles, timeout):
        states = tuple(self._state(handle, drain=True) for handle in handles)
        deadline = time.monotonic() + timeout / 1000
        self.api.pump(0, stop_after_source=False)
        while True:
            ready = tuple(i for i, state in enumerate(states) if state.queue or not state.connected)
            remaining = deadline - time.monotonic()
            if ready or remaining <= 0 or self.stopping.is_set():
                return ready
            seconds = min(remaining, _WAIT_SLICE)
            if self.api.pump(seconds, stop_after_source=True) == _LOOP_FINISHED:
                time.sleep(min(seconds, max(0, deadline - time.monotonic())))

    def close(self, handle):
        state = self.devices.pop(handle, None)
        if state is None:
            return
        self.open_ids.remove(handle.id)
        state.stop()
        self.api.cf.CFRelease(state.ref)
        self.api.cf.CFRelease(state.loop)
        state.input_callback = state.removal_callback = None

    def shutdown(self):
        self.stopping.set()
        with self.lock:
            for handle in tuple(self.devices):
                self.close(handle)
