"""Virtual joystick validation, state and recording shared by the Python runtimes."""
from dataclasses import dataclass
from threading import Lock

AXIS_CODES = {name: code for code, name in enumerate(
    "x y z rx ry rz throttle rudder wheel gas brake".split())}


class VinputProblem(Exception):
    def __init__(self, device, category):
        self.device, self.category = device, category


def valid_vinput_name(name):
    return 1 <= len(name.encode("utf-8")) <= 80


def axis_midpoint(axis):
    return (axis["min"] + axis["max"]) // 2


def vinput_spec(record):
    spec = dict(record.items)
    axes = [dict(axis.items) for axis in spec["axes"]]
    names = {axis["name"] for axis in axes}
    if (not valid_vinput_name(spec["name"])
            or not 0 <= spec["vendor"] <= 65535
            or not 0 <= spec["product"] <= 65535
            or len(axes) > 16 or len(names) != len(axes)
            or not names <= AXIS_CODES.keys()
            or any(axis["min"] >= axis["max"] for axis in axes)
            or not 0 <= spec["buttons"] <= 56 or not 0 <= spec["hats"] <= 4):
        raise VinputProblem("", "invalid-request")
    return {**spec, "axes": axes}


@dataclass(eq=False)
class VinputDev:
    id: str
    spec: dict
    axis_indices: dict
    pending: list
    sent: list
    output: object


def make_vinput_dev(device, spec, output):
    state = ([axis_midpoint(axis) for axis in spec["axes"]]
             + [False] * spec["buttons"] + [(0, 0)] * spec["hats"])
    indices = {axis["name"]: i for i, axis in enumerate(spec["axes"])}
    return VinputDev(device, spec, indices, state.copy(), state, output)


def changed_controls(dev):
    axes = dev.spec["axes"]
    buttons_end = len(axes) + dev.spec["buttons"]
    for i, (old, value) in enumerate(zip(dev.sent, dev.pending)):
        if old == value:
            continue
        if i < len(axes):
            yield ("axis", axes[i]["name"], value)
            continue
        if i < buttons_end:
            yield ("button", i - len(axes), value)
            continue
        yield ("hat", i - buttons_end, *value)


def update_axis(dev, name, value):
    index = dev.axis_indices.get(name)
    if index is None:
        raise VinputProblem(dev.id, "invalid-request")
    axis = dev.spec["axes"][index]
    if not axis["min"] <= value <= axis["max"]:
        raise VinputProblem(dev.id, "invalid-request")
    dev.pending[index] = value


def update_button(dev, index, value):
    if not 0 <= index < dev.spec["buttons"]:
        raise VinputProblem(dev.id, "invalid-request")
    dev.pending[len(dev.axis_indices) + index] = value


def update_hat(dev, index, x, y):
    if not (0 <= index < dev.spec["hats"] and -1 <= x <= 1 and -1 <= y <= 1):
        raise VinputProblem(dev.id, "invalid-request")
    dev.pending[len(dev.axis_indices) + dev.spec["buttons"] + index] = (x, y)


UPDATES = {"axis": update_axis, "button": update_button, "hat": update_hat}


class VinputAdapter:
    def __init__(self, backend):
        self.backend = backend
        self.now = getattr(backend, "now", None)
        self.devices = {}
        self.next_id = 1
        self.stopped = False
        self.lock = Lock()

    def create(self, record):
        if self.stopped:
            raise VinputProblem("", "disconnected")
        if not self.backend.supported:
            raise VinputProblem("", "unsupported")
        spec = vinput_spec(record)
        device = f"v{self.next_id}"
        output = self.backend.create(device, spec)
        dev = make_vinput_dev(device, spec, output)
        self.devices[dev] = None
        self.next_id += 1
        return dev

    def close(self, dev):
        if dev in self.devices:
            del self.devices[dev]
            dev.output.close()

    def invoke(self, op, *args):
        with self.lock:
            if op == "supports":
                return not self.stopped and self.backend.supported and args[0] == "create"
            if op == "create":
                return self.create(*args)
            if op == "close":
                self.close(*args)
                return None
            dev = args[0]
            if dev not in self.devices:
                raise VinputProblem(dev.id, "disconnected")
            if op == "sync":
                dev.output.frame(dev, list(changed_controls(dev)))
                dev.sent[:] = dev.pending
                return None
            UPDATES[op](dev, *args[1:])
            return None

    def shutdown(self):
        with self.lock:
            self.stopped = True
            for dev in tuple(self.devices):
                try:
                    self.close(dev)
                except VinputProblem:
                    continue


class UnsupportedVinput:
    supported = False


class RecordingVinput:
    supported = True

    def __init__(self, now, append):
        self.now, self.append = now, append

    def log(self, op, device, **fields):
        try:
            self.append({"at-ms": self.now(), "op": "vinput-" + op,
                         "dev": device, **fields})
        except OSError:
            raise VinputProblem("" if op == "create" else device, "io") from None

    def create(self, device, spec):
        self.log("create", device, **spec)
        return RecordedJoystick(self, device)


@dataclass
class RecordedJoystick:
    recorder: RecordingVinput
    device: str

    def frame(self, dev, events):
        self.recorder.log("frame", self.device, events=[list(event) for event in events])

    def close(self):
        self.recorder.log("close", self.device)
