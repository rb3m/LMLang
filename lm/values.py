"""Runtime values. Int=int, Bool=bool, Str=str, List=tuple, Unit=UNIT, variants/records below."""
from __future__ import annotations

from dataclasses import dataclass

from .printer import flat, float_text
from .sexpr import Atom
from .tree import Coll, items
from .vector import Vec


class Unit:
    def __repr__(self):
        return "unit"


UNIT = Unit()
INT_MIN, INT_MAX = -(2 ** 63), 2 ** 63 - 1  # Int is signed 64-bit (ADR-029/030)


def in_range(n: int) -> bool:
    return INT_MIN <= n <= INT_MAX


@dataclass(frozen=True)
class Var:
    mod: str  # "" for prelude variants
    name: str
    args: tuple = ()


@dataclass(frozen=True)
class Pair:
    a: object
    b: object


@dataclass(frozen=True)
class Rec:
    t: str  # qualified type name
    items: tuple  # ((field, value), ...) in declaration order


@dataclass(eq=False)
class Closure:
    params: tuple
    body: object
    env: dict
    mod: object


@dataclass(eq=False)
class Named:
    info: object


@dataclass(eq=False)
class PyFn:
    name: str
    f: object


class LmFail(Exception):
    def __init__(self, id, args=()):
        super().__init__(id)
        self.id, self.args_ = id, tuple(args)


class Violation(Exception):
    def __init__(self, code, node, fn, clause, args):
        super().__init__(code)
        self.code, self.node, self.fn, self.clause, self.args_ = code, node, fn, clause, args


class ProofViolation(Exception):
    """Runtime fault E-PROOF-VIOLATED: a proven-safe operation's invariant was violated."""
    code = "E-PROOF-VIOLATED"

    def __init__(self, site_info):
        super().__init__(site_info[3])
        self.file, self.line, self.col, self.path, self.fn_qual = site_info


class Overflow(Exception):
    """Runtime fault E-OVERFLOW: an Int operation left the signed 64-bit range. Never an LmFail."""
    code = "E-OVERFLOW"

    def __init__(self, op, operands):
        super().__init__(op)
        self.op, self.operands = op, tuple(operands)


class FloatFault(Overflow):
    """Runtime fault E-FLOAT: a Float operation produced NaN or an infinity (ADR-039 item 4)."""
    code = "E-FLOAT"


class Denied(Exception):
    def __init__(self, eff, fn):
        super().__init__(eff)
        self.eff, self.fn = eff, fn


def show(v) -> str:
    from .pat_compile import Pat

    if isinstance(v, Pat):
        return "<pat>"
    if v is True:
        return "true"
    if v is False:
        return "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return float_text(v)
    if isinstance(v, str):
        return flat(Atom("str", v))
    if isinstance(v, tuple):
        return "(list" + "".join(" " + show(x) for x in v) + ")"
    if isinstance(v, Vec):
        return "(vecof" + "".join(" " + show(x) for x in v) + ")"
    if v is UNIT:
        return "unit"
    if isinstance(v, Var):
        n = f"{v.mod}.{v.name}" if v.mod else v.name
        return f"({n}" + "".join(" " + show(a) for a in v.args) + ")" if v.args else n
    if isinstance(v, Rec):
        return f"(new {v.t}" + "".join(f" ({k} {show(x)})" for k, x in v.items) + ")"
    if isinstance(v, Pair):
        return f"(pair {show(v.a)} {show(v.b)})"
    if isinstance(v, Coll):
        return show_coll(v, show)
    return "<fn>"


def show_coll(v, part) -> str:
    """`(setof k..)` or `(mapof (k v)..)` in ascending key order; `part` prints keys and values."""
    if v.is_set:
        return "(setof" + "".join(" " + part(k) for k, _ in items(v.root)) + ")"
    return "(mapof" + "".join(f" ({part(k)} {part(x)})" for k, x in items(v.root)) + ")"


def show_args(args) -> str:
    return "(" + " ".join(show(a) for a in args) + ")"
