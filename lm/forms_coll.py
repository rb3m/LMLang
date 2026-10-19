"""Special forms `mapof` and `setof`: Map and Set literals with constant keys (ADR-049 item 4)."""
from __future__ import annotations

from .printer import flat
from .sexpr import Atom, SList
from .types import mapt, sett

KEY_LITERALS = ("int", "float", "str")


def key_literal(node) -> bool:
    """A constant usable as a `mapof` key or `setof` element: an Int, Float, Str or Bool literal."""
    if not isinstance(node, Atom):
        return False
    return node.kind in KEY_LITERALS or (node.kind == "sym" and node.value in ("true", "false"))


class CollFormsMixin:
    def _key(self, m, node, kt, seen, env, path):
        """Check one constant key against the shared key type `kt`; duplicates are E-DUP-NAME."""
        if not key_literal(node):
            self.diag(m, "E-TYPE", node, path, "keys of `mapof` and elements of `setof` must be Int, Float, Str or Bool literals",
                      expected="a literal constant", found=flat(node))
            return
        self.expect(m, kt, self.infer(m, node, env, path), node, path, "key")
        ident = (node.kind, node.value)
        if ident in seen:
            self.diag(m, "E-DUP-NAME", node, path, f"duplicate key {flat(node)}", found=flat(node))
        seen.add(ident)

    def f_mapof(self, m, e, env, path):
        k, v, seen = self.s.fresh(), self.s.fresh(), set()
        for i, pair in enumerate(e.items[1:], 1):
            pp = f"{path}/{i}"
            if not (isinstance(pair, SList) and len(pair.items) == 2):
                self._shape(m, pair, pp, "(key value) in (mapof (key value)...)")
                continue
            self._key(m, pair.items[0], k, seen, env, pp + "/0")
            self.expect(m, v, self.infer(m, pair.items[1], env, pp + "/1"), pair.items[1], pp + "/1", "map value")
        self.note_constraint("key", k, e, path)
        return mapt(k, v)

    def f_setof(self, m, e, env, path):
        k, seen = self.s.fresh(), set()
        for i, x in enumerate(e.items[1:], 1):
            self._key(m, x, k, seen, env, f"{path}/{i}")
        self.note_constraint("key", k, e, path)
        return sett(k)
