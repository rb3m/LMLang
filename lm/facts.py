"""Fact system for proven-safe division and indexing (ADR-061 item B)."""
from __future__ import annotations

from dataclasses import dataclass, field
from .sexpr import Atom, SList
from .types import INT

INT_MIN = -(2 ** 63)
INT_MAX = 2 ** 63 - 1

FLIP_OP = {">": "<=", ">=": "<", "<": ">=", "<=": ">", "=": "!=", "!=": "="}
REV_OP = {">": "<", ">=": "<=", "<": ">", "<=": ">=", "=": "=", "!=": "!="}


@dataclass(frozen=True)
class Binding:
    name: str
    identity: object


@dataclass(frozen=True)
class LenTerm:
    binding: Binding


Term = Binding | LenTerm


@dataclass
class Bounds:
    lo: int = INT_MIN
    hi: int = INT_MAX
    neq: set[int] = field(default_factory=set)

    def is_nonzero(self) -> bool:
        if self.lo > 0 or self.hi < 0:
            return True
        if 0 in self.neq:
            return True
        if self.lo == self.hi and self.lo != 0:
            return True
        return False

    def is_gt(self, k: int) -> bool:
        return self.lo > k

    def copy(self) -> Bounds:
        return Bounds(self.lo, self.hi, set(self.neq))

    def add_comparison(self, op: str, c: int):
        if op == "=":
            self.lo = max(self.lo, c)
            self.hi = min(self.hi, c)
        elif op == "!=":
            self.neq.add(c)
        elif op == ">":
            self.lo = max(self.lo, c + 1) if c < INT_MAX else INT_MAX + 1
        elif op == ">=":
            self.lo = max(self.lo, c)
        elif op == "<":
            self.hi = min(self.hi, c - 1) if c > INT_MIN else INT_MIN - 1
        elif op == "<=":
            self.hi = min(self.hi, c)
        self._normalize()

    def _normalize(self):
        for c in sorted(self.neq):
            if self.lo == c and c < INT_MAX:
                self.lo = c + 1
            if self.hi == c and c > INT_MIN:
                self.hi = c - 1
        if self.lo > 0 or self.hi < 0:
            self.neq.add(0)


class FactSet:
    def __init__(self):
        self.bounds: dict[Term, Bounds] = {}

    def get_bounds(self, term: Term) -> Bounds:
        if term not in self.bounds:
            self.bounds[term] = Bounds(lo=0, hi=INT_MAX) if isinstance(term, LenTerm) else Bounds(lo=INT_MIN, hi=INT_MAX)
        return self.bounds[term]

    def is_nonzero(self, term: Term) -> bool:
        b = self.bounds.get(term)
        return b.is_nonzero() if b is not None else False

    def is_gt(self, term: Term, k: int) -> bool:
        b = self.bounds.get(term)
        return b.is_gt(k) if b is not None else False

    def fork(self) -> FactSet:
        f = FactSet()
        f.bounds = {t: b.copy() for t, b in self.bounds.items()}
        return f

    def add_condition(self, node, bindings: dict[str, Binding], env=None, s=None, negated=False):
        if not negated and isinstance(node, SList) and len(node.items) >= 2:
            h = node.items[0]
            if isinstance(h, Atom) and h.value == "and":
                for item in node.items[1:]:
                    self.add_condition(item, bindings, env, s, negated=False)
                return
        if isinstance(node, SList) and len(node.items) == 2:
            h = node.items[0]
            if isinstance(h, Atom) and h.value == "not":
                self.add_condition(node.items[1], bindings, env, s, negated=not negated)
                return
        if not (isinstance(node, SList) and len(node.items) == 3):
            return
        h, left, right = node.items
        if not (isinstance(h, Atom) and h.kind == "sym" and h.value in FLIP_OP):
            return
        op = FLIP_OP[h.value] if negated else h.value

        t_left = extract_term(left, bindings, env, s)
        c_right = extract_int_lit(right)
        if t_left is not None and c_right is not None:
            self.get_bounds(t_left).add_comparison(op, c_right)
            return

        c_left = extract_int_lit(left)
        t_right = extract_term(right, bindings, env, s)
        if c_left is not None and t_right is not None:
            self.get_bounds(t_right).add_comparison(REV_OP[op], c_left)


def extract_int_lit(node) -> int | None:
    if isinstance(node, Atom) and node.kind == "int":
        return node.value
    return None


def extract_term(node, bindings: dict[str, Binding], env=None, s=None) -> Term | None:
    if isinstance(node, Atom) and node.kind == "sym":
        b = bindings.get(node.value)
        if b is not None:
            if env is not None and node.value in env and s is not None:
                t = s.walk(env[node.value])
                if t != INT and t[0] != "var":
                    return None
            return b
        return None
    if isinstance(node, SList) and len(node.items) == 2:
        h, arg = node.items
        if isinstance(h, Atom) and h.value == "len" and isinstance(arg, Atom) and arg.kind == "sym":
            b = bindings.get(arg.value)
            if b is not None:
                return LenTerm(b)
    return None
