"""Linux uinput adapter using the generic ioctl encoding and native event ABI."""
import errno
import os
import struct

from .vinput_adapter import AXIS_CODES, VinputProblem, axis_midpoint

EV_SYN, EV_KEY, EV_ABS = 0, 1, 3
ABS_HAT0X = 0x10
INPUT_EVENT = struct.Struct("@llHHi")
DEVICE_SETUP = struct.Struct("@HHHH80sI")
ABS_SETUP = struct.Struct("@H2xiiiiii")


def uinput_ioctl(number, size=0):
    return ((1 << 30) | (size << 16) if size else 0) | (ord("U") << 8) | number


UI_DEV_CREATE = uinput_ioctl(1)
UI_DEV_DESTROY = uinput_ioctl(2)
UI_DEV_SETUP = uinput_ioctl(3, DEVICE_SETUP.size)
UI_ABS_SETUP = uinput_ioctl(4, ABS_SETUP.size)
UI_SET_EVBIT = uinput_ioctl(100, 4)
UI_SET_KEYBIT = uinput_ioctl(101, 4)
UI_SET_ABSBIT = uinput_ioctl(103, 4)


def button_code(index):
    return 0x120 + index if index < 16 else 0x2c0 + index - 16


def error_category(ex):
    return {
        errno.EACCES: "permission", errno.EPERM: "permission",
        errno.ENOENT: "unsupported", errno.ENODEV: "unsupported",
        errno.EBUSY: "busy",
    }.get(ex.errno, "io")


def pack_device(spec):
    return DEVICE_SETUP.pack(6, spec["vendor"], spec["product"], 1,
                             spec["name"].encode("utf-8"), 0)


def pack_abs(code, value, low, high):
    return ABS_SETUP.pack(code, value, low, high, 0, 0, 0)


def pack_event(kind, code, value):
    return INPUT_EVENT.pack(0, 0, kind, code, value)


def absolute_controls(spec):
    for axis in spec["axes"]:
        yield AXIS_CODES[axis["name"]], axis_midpoint(axis), axis["min"], axis["max"]
    for offset in range(2 * spec["hats"]):
        yield ABS_HAT0X + offset, 0, -1, 1


def changed_hat_events(dev, index, x, y):
    offset = len(dev.axis_indices) + dev.spec["buttons"]
    for coordinate, (old, new) in enumerate(zip(dev.sent[offset + index], (x, y))):
        if old != new:
            yield pack_event(EV_ABS, ABS_HAT0X + 2 * index + coordinate, new)


def close_fd(fd):
    try:
        os.close(fd)
    except OSError as ex:
        return ex
    return None


def uinput_frame(dev, events):
    data = bytearray()
    for kind, key, value, *parts in events:
        if kind == "axis":
            data.extend(pack_event(EV_ABS, AXIS_CODES[key], value))
            continue
        if kind == "button":
            data.extend(pack_event(EV_KEY, button_code(key), value))
            continue
        data.extend(b"".join(changed_hat_events(dev, key, value, parts[0])))
    data.extend(pack_event(EV_SYN, 0, 0))
    return data


class LinuxVinput:
    supported = True

    def __init__(self, ioctl, path="/dev/uinput"):
        self.ioctl, self.path = ioctl, path

    def configure(self, fd, spec, controls):
        if spec["buttons"]:
            self.ioctl(fd, UI_SET_EVBIT, EV_KEY)
        if controls:
            self.ioctl(fd, UI_SET_EVBIT, EV_ABS)
        self.ioctl(fd, UI_SET_EVBIT, EV_SYN)
        for i in range(spec["buttons"]):
            self.ioctl(fd, UI_SET_KEYBIT, button_code(i))
        self.ioctl(fd, UI_DEV_SETUP, pack_device(spec))
        for code, payload in controls:
            self.ioctl(fd, UI_SET_ABSBIT, code)
            self.ioctl(fd, UI_ABS_SETUP, payload)
        self.ioctl(fd, UI_DEV_CREATE)

    def create(self, device, spec):
        try:
            controls = [(args[0], pack_abs(*args)) for args in absolute_controls(spec)]
        except struct.error:
            # Linux input_absinfo has signed 32-bit limits.
            raise VinputProblem("", "io") from None
        fd = None
        try:
            fd = os.open(self.path, os.O_WRONLY | os.O_NONBLOCK | os.O_CLOEXEC)
            self.configure(fd, spec, controls)
        except OSError as ex:
            if fd is not None:
                close_fd(fd)
            raise VinputProblem("", error_category(ex)) from None
        return LinuxJoystick(fd, device, self.ioctl)


class LinuxJoystick:
    def __init__(self, fd, device, ioctl):
        self.fd, self.device, self.ioctl = fd, device, ioctl

    def frame(self, dev, events):
        data = uinput_frame(dev, events)
        try:
            if os.write(self.fd, data) != len(data):
                raise OSError(errno.EIO, "short uinput write")
        except OSError as ex:
            raise VinputProblem(self.device, error_category(ex)) from None

    def close(self):
        destroy_error = None
        try:
            self.ioctl(self.fd, UI_DEV_DESTROY)
        except OSError as ex:
            destroy_error = ex
        close_error = close_fd(self.fd)
        error = destroy_error or close_error
        if error is not None:
            raise VinputProblem(self.device, error_category(error))
