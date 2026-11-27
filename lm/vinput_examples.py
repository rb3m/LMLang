"""Constant syntax for hermetic virtual joystick log checks."""
from .consts import ConstEvalError, ConstEvaluator
from .examples import clause_name
from .sexpr import SList
from .types import BOOL, INT, STR
from .vinput_adapter import AXIS_CODES, valid_vinput_name

ENTRIES = {"create": (INT, STR, STR), "frame": (INT, STR, None),
           "close": (INT, STR)}
EVENTS = {"axis": (STR, INT), "button": (INT, BOOL), "hat": (INT, INT, INT)}


def shape(node, schemas):
    name = clause_name(node)
    if name not in schemas:
        raise ValueError("unknown vinput log entry or event")
    types = schemas[name]
    if len(node.items) != len(types) + 1:
        raise ValueError(f"{name} takes {len(types)} values")
    return name, types


def entries(clause):
    for index, node in enumerate(clause.items[1:], 1):
        op, types = shape(node, ENTRIES)
        fields = [(expr, typ, f"{index}/{i}")
                  for i, (expr, typ) in enumerate(zip(node.items[1:], types), 1)
                  if typ is not None]
        events = frame_events(node.items[3], index) if op == "frame" else ()
        yield op, fields, events


def frame_events(group, index):
    if not isinstance(group, SList):
        raise ValueError("frame events must be a list")
    events = []
    for j, event in enumerate(group.items, 1):
        kind, types = shape(event, EVENTS)
        events.append((kind, [
            (expr, typ, f"{index}/3/{j}/{k}")
            for k, (expr, typ) in enumerate(zip(event.items[1:], types), 1)
        ]))
    return events

def check_vinput(metadata, clause, path):
    ck, m = metadata.ck, metadata.m
    try:
        rows = list(entries(clause))
    except ValueError as ex:
        metadata.error(clause, path, str(ex))
        return False

    def check_fields(fields):
        for expr, typ, suffix in fields:
            ep = f"{path}/{suffix}"
            ck.expect(m, typ, ck.infer(m, expr, {}, ep), expr, ep, "vinput log field")

    def run():
        for _, fields, events in rows:
            check_fields(fields)
            for _, values in events:
                check_fields(values)

    start = len(ck.prog.diags)
    ck.sandbox(m, "a vinput log clause", run)
    ck.check_eq(m)
    diags = ck.prog.diags[start:]
    del ck.prog.diags[start:]
    for diag in diags:
        metadata.error(clause, diag.path, diag.msg)
    return not diags


def check_event(kind, values):
    if kind == "axis" and values[0] not in AXIS_CODES:
        raise ValueError("unknown vinput axis name")
    if kind == "button" and not 0 <= values[0] < 56:
        raise ValueError("invalid vinput button index")
    if kind == "hat" and not (0 <= values[0] < 4 and
                              -1 <= values[1] <= 1 and -1 <= values[2] <= 1):
        raise ValueError("invalid vinput hat index or position")
    return [kind, *values]


def vinput_values(prog, mod, clause):
    evaluator = ConstEvaluator(prog)

    def evaluate(fields):
        return [evaluator.ev(expr, {}, mod) for expr, _, _ in fields]

    logs = []
    try:
        for op, fields, events in entries(clause):
            at, dev, *details = evaluate(fields)
            if at < 0 or not dev:
                raise ValueError("invalid vinput log time or device ID")
            row = {"at-ms": at, "op": "vinput-" + op, "dev": dev}
            if op == "create" and not valid_vinput_name(details[0]):
                raise ValueError("invalid vinput device name")
            if op == "create":
                row["name"] = details[0]
            if op == "frame":
                row["events"] = [check_event(kind, evaluate(values))
                                 for kind, values in events]
            logs.append(row)
    except ValueError as ex:
        raise ConstEvalError(str(ex)) from None
    return (logs,)
