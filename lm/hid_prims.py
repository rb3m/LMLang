"""Translate the LM HID prim contract to runtime adapter operations."""
import os

from .hid_adapter import INFO_FIELDS, MAX_TIMEOUT, HidProblem, UnavailableHid, report_id, report_length, valid_int
from .hid_os import os_hid
from .hid_replay import replay_hid
from .values import UNIT, LmFail, Rec, Var

OPS = ("enumerate", "open", "read", "write", "feature-get", "feature-set",
       "grab", "wait", "close", "supports")


def start_hid():
    if "LM_HID_REPLAY" in os.environ:
        return replay_hid(os.environ["LM_HID_REPLAY"], os.environ.get("LM_HID_REPLAY_LOG"))
    return os_hid()


def _invoke(adapter, op, args):
    if isinstance(adapter, UnavailableHid) and adapter.category == "io":
        return adapter.invoke(op, *args)
    if op in ("write", "feature-set"):
        dev, report = args
        fields = dict(report.items)
        args = dev, fields["id"], fields["data"]
        if not report_id(args[1]) or not report_length(len(args[2])):
            raise HidProblem(dev.id, "invalid-request")
    if op == "feature-get" and not (report_id(args[1]) and report_length(args[2])):
        raise HidProblem(args[0].id, "invalid-request")
    if op == "wait" and not valid_int(args[1], 0, MAX_TIMEOUT):
        raise HidProblem("", "invalid-request")
    return adapter.invoke(op, *args)


def hid_call(adapter, op, *args):
    try:
        value = _invoke(adapter, op, args)
    except HidProblem as ex:
        raise LmFail("hid.HidError", (ex.device, ex.category)) from None
    if op == "enumerate":
        return tuple(Rec("hid.Info", tuple(zip(INFO_FIELDS, item))) for item in value)
    if op == "read":
        if value is None:
            return Var("", "None")
        report = Rec("hid.Report", (("id", value[0]), ("data", value[1])))
        return Var("", "Some", (report,))
    return UNIT if value is None else value


def _prim(op):
    def run(it, *args):
        if it.hid is None:
            it.hid = start_hid()
        return hid_call(it.hid, op, *args)
    return run


HID_PRIMS = {"hid." + op: _prim(op) for op in OPS}
