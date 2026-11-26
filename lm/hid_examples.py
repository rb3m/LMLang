"""Constant syntax for hermetic HID traces and ordered log checks."""
from __future__ import annotations

from .consts import ConstEvalError, ConstEvaluator
from .examples import clause_name
from .hid_adapter import INFO_FIELDS, decode_report, report_id, report_length, valid_int
from .hid_replay import parse_trace
from .resolve import head
from .types import BOOL, INT, STR
from .values import INT_MAX


TRACE_FIELDS = {
    "device": (INFO_FIELDS, (STR, INT, INT, INT, INT, INT, STR, STR)),
    "report": (("at-ms", "dev", "report-id", "data"), (INT, STR, INT, STR)),
    "feature": (("at-ms", "dev", "feature-id", "data"), (INT, STR, INT, STR)),
    "unplug": (("at-ms", "dev"), (INT, STR)),
}
LOG_FIELDS = {
    "write": TRACE_FIELDS["report"],
    "feature-set": TRACE_FIELDS["feature"],
    "feature-get": (("at-ms", "dev", "feature-id", "len"), (INT, STR, INT, INT)),
    "grab": (("at-ms", "dev", "on"), (INT, STR, BOOL)),
    "close": TRACE_FIELDS["unplug"],
}


def _shape(name, row, log):
    schemas = LOG_FIELDS if log else TRACE_FIELDS
    if name not in schemas:
        raise ValueError("unknown HID example entry")
    fields, types = schemas[name]
    count = len(row.items) - 1
    if name == "device" and count == 5:
        return fields[:5], types[:5]
    if count != len(fields):
        raise ValueError(f"{name} takes {len(fields)} values")
    return fields, types


def check_hid(metadata, clause, path):
    ck, m = metadata.ck, metadata.m
    start = len(ck.prog.diags)
    log = head(clause) == "hid-log"

    def check_row(row, rp):
        name = clause_name(row)
        try:
            _, types = _shape(name, row, log)
        except ValueError as ex:
            metadata.error(row, rp, str(ex))
            return
        effects = {"hid.grab"} if name == "grab" else {"hid.io"}
        if log and not effects & metadata.f.eff:
            metadata.error(row, rp, f"{name} needs a declared {next(iter(effects))} effect")
        for i, (expr, typ) in enumerate(zip(row.items[1:], types), 1):
            ep = f"{rp}/{i}"
            ck.expect(m, typ, ck.infer(m, expr, {}, ep), expr, ep, "HID example entry")

    def run():
        for i, row in enumerate(clause.items[1:], 1):
            check_row(row, f"{path}/{i}")

    ck.sandbox(m, "a HID example clause", run)
    ck.check_eq(m)
    diags = ck.prog.diags[start:]
    del ck.prog.diags[start:]
    for d in diags:
        metadata.error(clause, d.path, d.msg)
    return not diags


def _log_row(name, row):
    if not valid_int(row["at-ms"], 0, INT_MAX) or not row["dev"]:
        raise ValueError("invalid HID log time or device id")
    for field in ("report-id", "feature-id"):
        if field in row and not report_id(row[field]):
            raise ValueError("invalid HID log report id")
    if "data" in row:
        row["data"] = decode_report(row["data"]).hex()
    if "len" in row and not report_length(row["len"]):
        raise ValueError("invalid HID feature request length")
    return {"op": name, **row}


def hid_values(prog, mod, clause):
    log = head(clause) == "hid-log"
    evaluator = ConstEvaluator(prog)
    trace = {"devices": [], "events": []}
    logs = []
    try:
        for node in clause.items[1:]:
            name = head(node)
            fields, _ = _shape(name, node, log)
            row = {key: evaluator.ev(expr, {}, mod)
                   for key, expr in zip(fields, node.items[1:])}
            if log:
                logs.append(_log_row(name, row))
                continue
            if name == "device":
                trace["devices"].append({"interface": -1, "name": "", "serial": "", **row})
                continue
            if name == "unplug":
                row["unplug"] = True
            trace["events"].append(row)
        return (logs if log else parse_trace(trace),)
    except ValueError as ex:
        raise ConstEvalError(str(ex)) from None
