"""Type constraint and equality checks mixed into Checker."""
from __future__ import annotations

from .prelude import CONSTRAINED
from .types import INT, UNIT, children, fn, keys_of, substitute


def contains_opaque(t, name, type_index, seen=frozenset()):
    """Inspect a resolved type, including substituted nominal fields."""
    if t[0] == name or (t[0] == "N" and t[1] == name):
        return True
    if t[0] != "N":
        return any(contains_opaque(c, name, type_index, seen)
                   for c in children(t))
    if t in seen:
        return False
    ti = type_index.get(t[1])
    if ti is None or getattr(ti, "invalid_recursion", False):
        return False
    mapping = dict(zip(ti.params, t[2:]))
    fields = list(ti.fields) + [x for v in ti.variants.values() for x in v.fields]
    return any(contains_opaque(substitute(ft, mapping), name, type_index,
                               seen | {t}) for _, ft in fields)


class TypeChecksMixin:
    def note_eq(self, t, node, path):
        self.__dict__.setdefault("eq_checks", []).append((t, node, path))

    def note_constraint(self, op, t, node, path):
        self.__dict__.setdefault("constraints", []).append((op, t, node, path))

    def note_keys(self, t, node, path):
        """Every Map key / Set element type inside an instantiated fn type is constrained (ADR-049 item 1)."""
        for k in keys_of(t, self.prog.type_index):
            self.note_constraint("key", k, node, path)

    def key_vars(self) -> set:
        """Type variables of the current fn's signature used as Map keys or Set elements: callers are
        checked when they instantiate them, so inside the fn they satisfy the key constraint (ADR-050)."""
        f = self.cur_fn
        sig = fn([t for _, t in f.params], f.ret) if f is not None and f.sig_ok else UNIT
        return {k[1] for k in keys_of(sig, self.prog.type_index) if k[0] == "V"}

    def check_constraints(self, m):
        bad_keys = set()  # one key diagnostic per type and fn: every call naming the Map/Set notes it
        for op, t, node, path in self.__dict__.get("constraints", []):
            if self.s.walk(t)[0] == "M":
                self.s.unify(t, INT)  # nothing fixes the operand type: default to Int
            got = self.s.show(t)
            allowed = CONSTRAINED[op]
            if got in allowed or (op == "key" and self.s.walk(t)[0] == "V" and got in self.key_vars()):
                continue
            if op == "key" and got in bad_keys:
                continue
            bad_keys.add(got if op == "key" else None)
            want = ", ".join(allowed[:-1]) + " or " + allowed[-1]
            what = "Map keys and Set elements must be" if op == "key" else f"`{op}` takes"
            self.diag(m, "E-TYPE", node, path, f"{what} {want}{'' if op == 'key' else ' operands'}, found {got}{'; suggest a Str key or nested maps' if op == 'key' and self.s.walk(t)[0] == 'Pair' else ''}", expected=want, found=got)
        self.constraints = []
        for m_mod, nm, t, node, path in self.__dict__.get("untyped_params", []):
            if self.has_meta(t):
                self.diag(m_mod, "E-TYPE", node, path, f"cannot infer type for lambda parameter `{nm}`; add a type annotation", expected="a concrete type", found="?")
        self.untyped_params = []

    def has_meta(self, t):
        t = self.s.walk(t)
        if t[0] == "M":
            return True
        return any(self.has_meta(c) for c in children(t))

    def check_eq(self, m):
        self.check_constraints(m)
        for t, node, path in self.eq_checks:
            if self.has_pat(t, set()):
                self.diag(m, "E-TYPE", node, path,
                          "`=`/`!=` cannot compare values containing Pat",
                          expected="a type without Pat", found=self.s.show(t))
            elif self.has_fn(t, set()):
                self.diag(m, "E-TYPE", node, path, f"`=`/`!=` cannot compare values containing functions ({self.s.show(self.s.resolve(t))})",
                          expected="a type without Fn", found=self.s.show(self.s.resolve(t)))
        self.eq_checks = []

    def has_fn(self, t, seen):
        return self.has_opaque(t, seen, "Fn")

    def has_pat(self, t, seen):
        return self.has_opaque(t, seen, "pat.Pat")

    def has_opaque(self, t, seen, name):
        return contains_opaque(self.s.resolve(t), name, self.prog.type_index,
                               frozenset(seen))

    def variant_type(self, m, vi, node, path, callable_value=False):
        """Fresh constructor parameters are shared by its fields and result."""
        template = fn([t for _, t in vi.fields], vi.vtype)
        ft = self.s.inst(template, {})
        self.note_keys(ft, node, path)
        return ft if callable_value and vi.fields else ft[2]
