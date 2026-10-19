"""The closed prelude (docs/SPEC.md section 7) and reserved words."""
from __future__ import annotations

from .types import BOOL, INT, KEY, NUMERIC, ORDERED, fn, lst, pair, var

_a, _b, _n = var("a"), var("b"), var("n")
VALUES = {
    "+": fn([_n, _n], _n),
    "-": fn([_n, _n], _n),
    "*": fn([_n, _n], _n),
    "/": fn([_n, _n], _n),
    "mod": fn([INT, INT], INT),
    "=": fn([_a, _a], BOOL),
    "!=": fn([_a, _a], BOOL),
    "<": fn([_n, _n], BOOL),
    "<=": fn([_n, _n], BOOL),
    ">": fn([_n, _n], BOOL),
    ">=": fn([_n, _n], BOOL),
    "not": fn([BOOL], BOOL),
    "len": fn([lst(_a)], INT),
    "cons": fn([_a, lst(_a)], lst(_a)),
    "pair": fn([_a, _b], pair(_a, _b)),
}
FAILING = {"/": "DivZero", "mod": "DivZero"}  # `/` fails DivZero only on Int operands (ADR-039 item 3)
# Allowed operand types of the operators whose type variable `n` is constrained (checked after unification).
# "key" is the Map key / Set element constraint (ADR-049 item 1); it is not a prelude name.
CONSTRAINED = {**{op: NUMERIC for op in "+-*/"}, **{op: ORDERED for op in ("<", "<=", ">", ">=")}, "key": KEY}
SPECIAL = frozenset(["if", "let", "let?", "do", "match", "lam", "list", "new", "get", "with", "and", "or", "fail", "try", "catch", "note", "prim", "mapof", "setof", "for"])
LITERALS = frozenset(["true", "false", "unit"])
RESERVED_VALUES = SPECIAL | LITERALS | frozenset(VALUES) | {"result"}
RESERVED_CAPS = frozenset(["Int", "Bool", "Str", "Unit", "Float", "List", "Opt", "Map", "Set", "Fn", "Some", "None", "DivZero", "OutOfRange", "Pair"])
EFFECTS = frozenset(["io.out", "io.in", "env.read", "fs.read", "fs.write", "fs.delete", "time.now", "rand"])


def form_method(prefix: str, form: str) -> str:
    """Method name for a special form in a per-form dispatcher: `let?` -> `f_let_q`."""
    return prefix + form.replace("?", "_q")
