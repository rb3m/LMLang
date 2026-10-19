"""Target-neutral IR produced by `lower.py` and consumed by backends (ADR-026 Decision 2, ADR-035).

Names are LM names (fn ids are qualified `mod.name`, constructor ids `mod.Name` or prelude `Some`,
record ids `mod.Type`, error ids as the interpreter spells them); backends mangle them. Expressions
are a tree (no statement form): each backend linearizes as its target needs. Evaluation order is
left to right exactly as written in the tree.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Site:
    """Source position of a node, for runtime faults (file, line, col, node path, enclosing fn)."""
    file: str
    line: int
    col: int
    path: str
    fn: str


@dataclass
class Lit:
    kind: str  # int | float | str | bool | unit
    value: object


@dataclass
class Local:
    name: str


@dataclass
class ConstRef:  # a module constant used as a value
    cid: str


@dataclass
class FnRef:  # a named function used as a value
    fid: str


@dataclass
class PreludeRef:  # a prelude operator used as a value (`+` passed to list.fold)
    op: str


@dataclass
class Call:  # direct call of a named function
    fid: str
    args: list
    site: Site | None = None
    discharged: bool = False


@dataclass
class TailCall:  # loop back to the enclosing fn, after evaluating every argument
    args: list


@dataclass
class PrimOp:  # prelude operator applied: + - * / mod = != < <= > >= not len cons
    op: str
    args: list
    site: Site
    discharged: bool = False


@dataclass
class Apply:  # call of a function value
    fn: object
    args: list


@dataclass
class If:
    cond: object
    then: object
    else_: object


@dataclass
class Let:  # one binding; sequential `let` lowers to nested Lets
    name: str
    value: object
    body: object


@dataclass
class Do:  # evaluate items in order; the value is the last one (unit when empty)
    items: list


@dataclass
class For:  # for x in list: evaluate body (Unit)
    name: str
    list: object
    body: object


@dataclass
class Test:
    """One check on the match subject. `path` is a tuple of steps from the subject:
    ("arg", k) variant argument k, ("elem", k) list element k, ("tail",) list without its head."""
    path: tuple
    kind: str  # tag | int | str | bool | len (list has exactly value elements) | nonempty
    value: object  # ctor id | int | str | bool | int | None


@dataclass
class Arm:
    tests: list  # all must hold (in order; a tag test precedes tests on its arguments)
    binds: list  # [(name, path)]
    body: object


@dataclass
class Match:  # arms tried in order; the checker guarantees one matches
    subject: object
    arms: list


@dataclass
class Lambda:
    params: list
    captures: list  # free locals of the body, sorted
    body: object


@dataclass
class ListLit:
    items: list


@dataclass
class MapLit:  # `(mapof ..)`: constant keys (Lits), values evaluated left to right (ADR-049)
    keys: list
    items: list


@dataclass
class SetLit:  # `(setof ..)`: constant elements (Lits)
    items: list


@dataclass
class Construct:  # variant value; nullary when args is empty
    ctor: str
    args: list


@dataclass
class NewRec:
    rtype: str
    fields: list  # [(field, expr)] in written (evaluation) order; backends place by declaration order


@dataclass
class GetField:
    rec: object
    field: str


@dataclass
class With:
    rec: object
    updates: list  # [(field, expr)] in written order


@dataclass
class And:
    items: list


@dataclass
class Or:
    items: list


@dataclass
class Fail:  # raise a recoverable LM error
    err: str
    args: list


@dataclass
class Handler:
    err: str
    names: list
    body: object


@dataclass
class Try:  # catches only LM failures whose id is handled; faults always propagate
    body: object
    handlers: list


@dataclass
class Contract:
    expr: object
    site: Site  # clause node; site.path is `mod/fn/requires#k`
    code: str  # E-REQUIRES-VIOLATED | E-ENSURES-VIOLATED


@dataclass
class Fn:
    fid: str
    params: list
    body: object | None  # None when prim is set
    prim: str | None
    requires: list = field(default_factory=list)  # [Contract]
    ensures: list = field(default_factory=list)  # [Contract]; `result` is bound
    tail: bool = False  # body contains a self TailCall


@dataclass
class Const:
    cid: str
    expr: object


@dataclass
class Program:
    fns: dict = field(default_factory=dict)  # fid -> Fn (only reachable ones)
    consts: dict = field(default_factory=dict)  # cid -> Const
    const_order: list = field(default_factory=list)  # [cid] in evaluation dependency order
    records: dict = field(default_factory=dict)  # rtype -> [field names] in declaration order
    ctors: dict = field(default_factory=dict)  # ctor id -> arity (non-prelude ones)
    errors: set = field(default_factory=set)  # error ids raised or caught
    prims: set = field(default_factory=set)  # prim names used
    stdlib: set = field(default_factory=set)  # names of standard-library modules (for fault frames)


def children(e):
    """Direct sub-expressions of an IR expression (for generic walks)."""
    if isinstance(e, (Call, TailCall, PrimOp, Construct, ListLit, MapLit, SetLit, And, Or, Fail, Do)):
        return list(getattr(e, "args", None) or getattr(e, "items", []))
    if isinstance(e, Apply):
        return [e.fn, *e.args]
    if isinstance(e, If):
        return [e.cond, e.then, e.else_]
    if isinstance(e, Let):
        return [e.value, e.body]
    if isinstance(e, Match):
        return [e.subject, *(a.body for a in e.arms)]
    if isinstance(e, Lambda):
        return [e.body]
    if isinstance(e, NewRec):
        return [x for _, x in e.fields]
    if isinstance(e, GetField):
        return [e.rec]
    if isinstance(e, With):
        return [e.rec, *(x for _, x in e.updates)]
    if isinstance(e, Try):
        return [e.body, *(h.body for h in e.handlers)]
    if isinstance(e, For):
        return [e.list, e.body]
    return []


def free_locals(e, bound=frozenset()) -> set:
    """Locals referenced in e and not bound inside it."""
    if isinstance(e, Local):
        return set() if e.name in bound else {e.name}
    if isinstance(e, Let):
        return free_locals(e.value, bound) | free_locals(e.body, bound | {e.name})
    if isinstance(e, For):
        return free_locals(e.list, bound) | free_locals(e.body, bound | {e.name})
    if isinstance(e, Lambda):
        return free_locals(e.body, bound | set(e.params))
    if isinstance(e, Match):
        out = free_locals(e.subject, bound)
        for a in e.arms:
            out |= free_locals(a.body, bound | {n for n, _ in a.binds})
        return out
    if isinstance(e, Try):
        out = free_locals(e.body, bound)
        for h in e.handlers:
            out |= free_locals(h.body, bound | set(h.names))
        return out
    out: set = set()
    for c in children(e):
        out |= free_locals(c, bound)
    return out
