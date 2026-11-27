"""Translate the LM vinput prim contract and select its adapter."""
import os
import sys
import time

from . import vinput_linux
from .device_replay import replay_log_writer
from .values import UNIT, LmFail
from .vinput_adapter import RecordingVinput, UnsupportedVinput, VinputAdapter, VinputProblem

VINPUT_OPS = ("create", "axis", "button", "hat", "sync", "close", "supports")


def start_vinput(hid):
    if "LM_HID_REPLAY" in os.environ:
        start = time.monotonic_ns()
        now = getattr(hid, "now", None) or (
            lambda: (time.monotonic_ns() - start) // 1_000_000)
        return VinputAdapter(RecordingVinput(now, replay_log_writer(
            os.environ.get("LM_HID_REPLAY_LOG"))))
    if sys.platform.startswith("linux"):
        import fcntl
        return VinputAdapter(vinput_linux.LinuxVinput(fcntl.ioctl))
    return VinputAdapter(UnsupportedVinput())


def vinput_call(adapter, op, *args):
    try:
        result = adapter.invoke(op, *args)
    except VinputProblem as ex:
        raise LmFail("vinput.VinputError", (ex.device, ex.category)) from None
    return UNIT if result is None else result


def _prim(op):
    def run(it, *args):
        if it.vinput is None:
            it.vinput = start_vinput(it.hid)
        return vinput_call(it.vinput, op, *args)
    return run


VINPUT_PRIMS = {"vinput." + op: _prim(op) for op in VINPUT_OPS}
