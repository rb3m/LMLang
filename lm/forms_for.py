"""Special form: for (ADR-060)."""
from __future__ import annotations

from .facts import Binding
from .sexpr import Atom, SList
from .types import UNIT, lst


class ForFormsMixin:
    def f_for(self, m, e, env, path):
        """`(for (x xs) body)`: evaluate xs once; bind x per element; body must be Unit (ADR-060)."""
        it = e.items
        if len(it) != 3 or not isinstance(it[1], SList):
            return self._shape(m, e, path, "(for (name expr) body)")
        b = it[1]
        if len(b.items) != 2 or not (isinstance(b.items[0], Atom) and b.items[0].kind == "sym"):
            return self._shape(m, b, path + "/1", "(name expr)")
        x_atom = b.items[0]
        name = x_atom.value
        self.local_ok(m, name, x_atom, path + "/1/0", env)
        xs_node = b.items[1]
        body_node = it[2]
        xs_t = self.infer(m, xs_node, env, path + "/1/1")
        elem_t = self.s.fresh()
        self.expect(m, lst(elem_t), xs_t, xs_node, path + "/1/1", "collection in `for` must be a List")

        self.in_for = getattr(self, "in_for", 0) + 1
        saved_effs, saved_frames = self.effs, self.frames
        self.effs, self.frames = {}, [{}]
        sb = dict(self.bindings)
        try:
            self.bindings[name] = Binding(name, id(e))
            body_t = self.infer(m, body_node, {**env, name: elem_t}, path + "/2")
        finally:
            self.bindings = sb
            self.in_for -= 1
            body_effs, body_fails = self.effs, self.frames[0]
            self.effs, self.frames = saved_effs, saved_frames
            for k, v in body_effs.items():
                self.effs.setdefault(k, v)
            for k, v in body_fails.items():
                self.frames[-1].setdefault(k, v)

        if self.expect(m, UNIT, body_t, body_node, path + "/2", "body of `for` must be Unit"):
            if not body_effs and not body_fails:
                self.diag(m, "W-FOR-PURE", body_node, path + "/2", "body of `for` has no effect and cannot fail; its result is discarded")
        return UNIT
