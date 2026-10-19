"""Type representation and unification. Types are tuples: (tag, ...)."""
from __future__ import annotations

INT, BOOL, STR, UNIT, NEVER = ("Int",), ("Bool",), ("Str",), ("Unit",), ("Never",)
FLOAT = ("Float",)
BASE = {"Int": INT, "Float": FLOAT, "Bool": BOOL, "Str": STR, "Unit": UNIT}
# Constraints on prelude operator type variables, checked once a fn's types are solved (ADR-039 item 3).
NUMERIC, ORDERED = ("Int", "Float"), ("Int", "Float", "Str")
KEY = ("Int", "Float", "Str", "Bool")  # Map keys and Set elements (ADR-049 item 1)
CONTAINERS = ("List", "Opt", "Set", "Map", "Pair")  # (tag, child..)


def lst(t):
    return ("List", t)


def opt(t):
    return ("Opt", t)


def pair(a, b):
    return ("Pair", a, b)


def mapt(k, v):
    return ("Map", k, v)


def sett(a):
    return ("Set", a)


def keys_of(t) -> list:
    """Key types of every Map/Set inside t (t not walked: for signatures and instantiated fn types)."""
    out = [t[1]] if t[0] in ("Map", "Set") else []
    for c in children(t):
        out += keys_of(c)
    return out


def children(t) -> tuple:
    if t[0] in CONTAINERS:
        return t[1:]
    if t[0] == "Fn":
        return (*t[1], t[2])
    return ()


def fn(args, ret):
    return ("Fn", tuple(args), ret)


def nom(q):
    return ("N", q)


def var(n):
    return ("V", n)


class Subst:
    def __init__(self):
        self.m: dict = {}
        self.n = 0

    def fresh(self):
        self.n += 1
        return ("M", self.n)

    def walk(self, t):
        while t[0] == "M" and t[1] in self.m:
            t = self.m[t[1]]
        return t

    def resolve(self, t):
        t = self.walk(t)
        return self._rebuild(t, self.resolve)

    @staticmethod
    def _rebuild(t, f):
        if t[0] in CONTAINERS:
            return (t[0], *(f(c) for c in t[1:]))
        if t[0] == "Fn":
            return ("Fn", tuple(f(a) for a in t[1]), f(t[2]))
        return t

    def _occurs(self, n, t):
        t = self.walk(t)
        if t[0] == "M":
            return t[1] == n
        return any(self._occurs(n, c) for c in children(t))

    def unify(self, a, b) -> bool:
        a, b = self.walk(a), self.walk(b)
        if a == b or a[0] == "Never" or b[0] == "Never":
            return True
        if a[0] == "M" or b[0] == "M":
            m, t = (a, b) if a[0] == "M" else (b, a)
            if self._occurs(m[1], t):
                return False
            self.m[m[1]] = t
            return True
        if a[0] != b[0]:
            return False
        if a[0] in CONTAINERS:
            return all(self.unify(x, y) for x, y in zip(a[1:], b[1:]))
        if a[0] == "Fn":
            return len(a[1]) == len(b[1]) and all(self.unify(x, y) for x, y in zip(a[1], b[1])) and self.unify(a[2], b[2])
        return False  # base/N/V equal case handled by a == b

    def join(self, a, b):
        """Result type of two branches; Never yields to the other branch."""
        if self.walk(a)[0] == "Never":
            return b
        return a

    def inst(self, t, mapping: dict):
        """Replace type variables by fresh metas (shared via mapping)."""
        tag = t[0]
        if tag == "V":
            if t[1] not in mapping:
                mapping[t[1]] = self.fresh()
            return mapping[t[1]]
        return self._rebuild(t, lambda c: self.inst(c, mapping))

    def show(self, t) -> str:
        t = self.resolve(t)
        tag = t[0]
        if tag in ("Int", "Float", "Bool", "Str", "Unit", "Never"):
            return tag
        if tag in CONTAINERS:
            return f"({tag} " + " ".join(self.show(c) for c in t[1:]) + ")"
        if tag == "Fn":
            return "(Fn (" + " ".join(self.show(a) for a in t[1]) + ") " + self.show(t[2]) + ")"
        if tag in ("N", "V"):
            return t[1]
        return "?"
