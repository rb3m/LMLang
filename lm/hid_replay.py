"""Replay and fake HID adapters over one validated trace and queue model."""
from __future__ import annotations

from collections import deque
import json
import threading
import time

from .hid_adapter import CAPS, INFO_FIELDS, MAX_QUEUE, HidDev, HidProblem, UnavailableHid
from .hid_adapter import decode_report, report_id, valid_int

INT_MAX = (1 << 63) - 1
INT_MIN = -(1 << 63)


def _device(row):
    if not isinstance(row, dict) or row.keys() != set(INFO_FIELDS):
        raise ValueError("invalid HID device fields")
    if not all(type(row[key]) is str for key in ("id", "name", "serial")):
        raise ValueError("invalid HID device text")
    for key in ("id", "name", "serial"):
        row[key].encode("utf-8", errors="strict")
    if not row["id"] or not all(valid_int(row[key], INT_MIN, INT_MAX)
                                for key in INFO_FIELDS[1:6]):
        raise ValueError("expected a nonempty device id and Int64 metadata")
    return tuple(row[key] for key in INFO_FIELDS)


def _event(row, ids):
    if not isinstance(row, dict):
        raise ValueError("invalid HID event")
    at, device = row.get("at-ms"), row.get("dev")
    if not valid_int(at, 0, INT_MAX) or not isinstance(device, str) or device not in ids:
        raise ValueError("invalid HID event time or device")
    fields = row.keys() - {"at-ms", "dev"}
    if fields == {"unplug"} and row["unplug"] is True:
        return at, device, "unplug", 0, b""
    kinds = ("report-id", "feature-id")
    for key in kinds:
        if fields == {key, "data"} and report_id(row[key]):
            return at, device, key, row[key], decode_report(row["data"])
    raise ValueError("invalid HID event fields or report id")


def parse_trace(trace):
    if not isinstance(trace, dict) or trace.keys() != {"devices", "events"}:
        raise ValueError("expected HID devices and events")
    if not all(isinstance(value, list) for value in trace.values()):
        raise ValueError("HID devices and events must be arrays")
    devices = [_device(row) for row in trace["devices"]]
    ids = {row[0] for row in devices}
    if len(ids) != len(devices):
        raise ValueError("duplicate HID device id")
    events = [_event(row, ids) for row in trace["events"]]
    return devices, sorted(events, key=lambda event: event[0])


def _unique_keys(entries):
    obj = dict(entries)
    if len(obj) != len(entries):
        raise ValueError("duplicate JSON key")
    return obj


def replay_hid(path, log_path):
    try:
        with open(path, encoding="utf-8") as stream:
            trace = parse_trace(json.load(stream, object_pairs_hook=_unique_keys))
    except (OSError, ValueError, RecursionError):
        return UnavailableHid("io")
    start = time.monotonic_ns()

    def now():
        return (time.monotonic_ns() - start) // 1_000_000

    def append(row):
        if log_path is not None:
            with open(log_path, "a", encoding="utf-8") as stream:
                stream.write(json.dumps(row, ensure_ascii=False) + "\n")

    return LiveReplayHid(trace, now, append)


class ReplayDevice:
    def __init__(self, info):
        self.info = info
        self.attached = True
        self.queue = deque(maxlen=MAX_QUEUE)
        self.features = {}
        self.handle = None


class ReplayHid:
    def __init__(self, trace, now, sleep, append):
        devices, events = trace
        self.devices = {info[0]: ReplayDevice(info) for info in devices}
        self.events = deque(events)
        self.now, self.sleep, self.append = now, sleep, append
        self.handles = {}
        self.operations = {
            "enumerate": self.enumerate, "open": self.open, "read": self.read,
            "write": self.write, "feature-get": self.feature_get,
            "feature-set": self.feature_set, "grab": self.grab, "wait": self.wait,
            "close": self.close, "supports": CAPS.__contains__,
        }

    def invoke(self, op, *args):
        self.advance(self.now())
        return self.operations[op](*args)

    def advance(self, through):
        while self.events and self.events[0][0] <= through:
            self.apply_event(self.events.popleft())

    def apply_event(self, event):
        _, device, kind, ident, data = event
        state = self.devices[device]
        if not state.attached:
            return
        if kind == "unplug":
            state.attached = False
            return
        if kind == "report-id":
            state.queue.append((ident, data))
            return
        state.features[ident] = data

    def enumerate(self):
        return tuple(state.info for state in self.devices.values() if state.attached)

    def open(self, device):
        state = self.devices.get(device)
        if state is None or not state.attached:
            raise HidProblem(device, "not-found")
        if state.handle is not None:
            raise HidProblem(device, "busy")
        handle = HidDev(device)
        state.handle = handle
        self.handles[handle] = state
        return handle

    def state(self, handle, *, drain=False):
        state = self.handles.get(handle)
        if state is None or (not drain and not state.attached):
            raise HidProblem(handle.id, "disconnected")
        return state

    def read(self, handle):
        state = self.state(handle, drain=True)
        if state.queue:
            return state.queue.popleft()
        if not state.attached:
            raise HidProblem(handle.id, "disconnected")
        return None

    def log(self, op, handle, **fields):
        row = {"at-ms": self.now(), "op": op, "dev": handle.id, **fields}
        try:
            self.append(row)
        except (OSError, ValueError):
            raise HidProblem(handle.id, "io") from None

    def write(self, handle, ident, data):
        self.state(handle)
        self.log("write", handle, **{"report-id": ident, "data": data.hex()})

    def feature_set(self, handle, ident, data):
        self.state(handle)
        self.log("feature-set", handle, **{"feature-id": ident, "data": data.hex()})

    def feature_get(self, handle, ident, length):
        state = self.state(handle)
        self.log("feature-get", handle, **{"feature-id": ident, "len": length})
        if ident not in state.features:
            raise HidProblem(handle.id, "not-found")
        return state.features[ident][:length]

    def grab(self, handle, on):
        self.state(handle)
        self.log("grab", handle, on=on)

    def wait(self, handles, timeout):
        devices = tuple(self.state(handle, drain=True) for handle in handles)
        deadline = self.now() + timeout
        while True:
            now = self.now()
            self.advance(min(now, deadline))
            ready = tuple(i for i, state in enumerate(devices)
                          if state.queue or not state.attached)
            if ready or now >= deadline:
                return ready
            wake = min(deadline, self.events[0][0]) if self.events else deadline
            self.sleep(wake - now)

    def close(self, handle):
        state = self.handles.pop(handle, None)
        if state is None:
            return
        state.handle = None
        self.log("close", handle)

    def shutdown(self):
        for handle in tuple(self.handles):
            try:
                self.close(handle)
            except HidProblem:
                continue


class LiveReplayHid(ReplayHid):
    """Serialize operations with shutdown and let shutdown interrupt sleep."""

    def __init__(self, trace, now, append):
        self.lock = threading.Lock()
        self.stopping = threading.Event()
        super().__init__(trace, now, self.pause, append)

    def pause(self, ms):
        if self.stopping.wait(ms / 1000):
            raise HidProblem("", "io")

    def invoke(self, op, *args):
        with self.lock:
            if self.stopping.is_set():
                return UnavailableHid("io").invoke(op, *args)
            return super().invoke(op, *args)

    def shutdown(self):
        self.stopping.set()
        with self.lock:
            super().shutdown()
