"""Special form: match."""
from __future__ import annotations

from .facts import Binding
from .printer import flat
from .sexpr import Atom, SList
from .types import BOOL, FLOAT, INT, NEVER, STR, UNIT, lst, pair


class MatchFormsMixin:
    # ---- match ---------------------------------------------------------------------------------
    def f_match(self, m, e, env, path):
        it = e.items
        if len(it) < 3:
            return self._shape(m, e, path, "(match expr (pattern body)...)")
        st = self.infer(m, it[1], env, path + "/1")
        res, covers = None, []
        for i, arm in enumerate(it[2:], 2):
            ap = f"{path}/{i}"
            if not (isinstance(arm, SList) and len(arm.items) == 2):
                self._shape(m, arm, ap, "(pattern body)")
                continue
            binds: dict = {}
            covers.append(self.pattern(m, arm.items[0], st, binds, env, ap + "/0"))
            sb = dict(self.bindings)
            try:
                for bname in binds:
                    self.bindings[bname] = Binding(bname, id(arm))
                bt = self.infer(m, arm.items[1], {**env, **binds}, ap + "/1")
            finally:
                self.bindings = sb
            if res is None or self.s.walk(res)[0] == "Never":
                res = bt
            else:
                self.expect(m, res, bt, arm.items[1], ap + "/1", "match arms must have the same type")
        self.exhaustive(m, st, covers, e, path)
        return res if res is not None else self.s.fresh()

    def pattern(self, m, p, t, binds, env, path):
        if isinstance(p, Atom):
            if p.kind == "int":
                self.int_range(m, p, path)
                self.expect(m, t, INT, p, path, "pattern")
                return ("lit", ("int", p.value))
            if p.kind == "float":
                self.float_range(m, p, path)
                self.expect(m, t, FLOAT, p, path, "pattern")
                self.diag(m, "E-TYPE", p, path, "Float literals are not allowed in patterns; compare with < <= = instead",
                          expected="a comparison", found=flat(p))
                return ("lit", ("float", p.value))
            if p.kind == "str":
                self.expect(m, t, STR, p, path, "pattern")
                return ("lit", ("str", p.value))
            if p.kind == "sym":
                v = p.value
                if v == "_":
                    return ("any",)
                if v in ("true", "false"):
                    self.expect(m, t, BOOL, p, path, "pattern")
                    return ("lit", ("bool", v))
                if v == "unit":
                    self.expect(m, t, UNIT, p, path, "pattern")
                    return ("any",)
                self.local_ok(m, v, p, path, env, binds)
                binds[v] = t
                return ("any",)
            return self.pat_ctor(m, p, [], t, binds, env, path)
        if p.items and isinstance(p.items[0], Atom):
            if p.items[0].kind == "type":
                return self.pat_ctor(m, p.items[0], p.items[1:], t, binds, env, path)
            if p.items[0].kind == "sym" and p.items[0].value in ("list", "cons"):
                return self.pat_list(m, p, t, binds, env, path)
            if p.items[0].kind == "sym" and p.items[0].value == "pair":
                return self.pat_pair(m, p, t, binds, env, path)
        self._shape(m, p, path, "a pattern: literal, name, _, Variant, (Variant pattern...), (list pattern...), (cons h t) or (pair a b)")
        return ("any",)

    def pat_pair(self, m, p, t, binds, env, path):
        a, b = self.s.fresh(), self.s.fresh()
        self.expect(m, t, pair(a, b), p, path, "pattern")
        subs = p.items[1:]
        if not self.arity(m, "pattern `pair`", 2, len(subs), p, path):
            return ("ctor", ("", "pair"), False)
        c1 = self.pattern(m, subs[0], a, binds, env, f"{path}/1")
        c2 = self.pattern(m, subs[1], b, binds, env, f"{path}/2")
        return ("ctor", ("", "pair"), c1[0] == "any" and c2[0] == "any")

    def pat_list(self, m, p, t, binds, env, path):
        el = self.s.fresh()
        self.expect(m, t, lst(el), p, path, "pattern")
        subs = p.items[1:]
        if p.items[0].value == "list":
            irref = True
            for i, sp in enumerate(subs, 1):
                c = self.pattern(m, sp, el, binds, env, f"{path}/{i}")
                irref = irref and c[0] == "any"
            return ("ctor", ("", "nil"), True) if not subs else ("list", len(subs), irref)
        if not self.arity(m, "pattern `cons`", 2, len(subs), p, path):
            return ("ctor", ("", "cons"), False)
        c1 = self.pattern(m, subs[0], el, binds, env, f"{path}/1")
        c2 = self.pattern(m, subs[1], lst(el), binds, env, f"{path}/2")
        return ("ctor", ("", "cons"), c1[0] == "any" and c2[0] == "any")

    def pat_ctor(self, m, name, subs, t, binds, env, path):
        hit = self.find_cap(m, name.value, ("variant",), name, path)
        if hit is None:
            return ("any",)
        vi, mp = hit[1], {}
        self.prog.refs[(m.name, path)] = f"{vi.mod.name}.{vi.name}" if vi.mod.name else vi.name
        self.expect(m, t, self.s.inst(vi.vtype, mp), name, path, "pattern")
        self.note_keys(t, name, path)
        key = (vi.mod.name, vi.name)
        if not self.arity(m, f"variant `{name.value}`", len(vi.fields), len(subs), name, path):
            return ("ctor", key, False)
        irref = True
        for i, (sp, (_, ft)) in enumerate(zip(subs, vi.fields), 1):
            c = self.pattern(m, sp, self.s.inst(ft, mp), binds, env, f"{path}/{i}")
            irref = irref and c[0] == "any"
        return ("ctor", key, irref)

    def exhaustive(self, m, st, covers, node, path):
        if any(c[0] == "any" for c in covers):
            return
        t = self.s.walk(st)
        full = {c[1] for c in covers if c[0] == "ctor" and c[2]}
        lits = {c[1][1] for c in covers if c[0] == "lit" and c[1][0] == "bool"}
        missing = None
        if t[0] == "Bool":
            missing = [x for x in ("true", "false") if x not in lits]
        elif t[0] == "Opt":
            missing = [n for n in ("Some", "None") if ("", n) not in full]
        elif t[0] == "Pair":
            missing = ["(pair _ _)"] if ("", "pair") not in full else []
        elif t[0] == "List":
            missing = [lbl for k, lbl in ((("", "nil"), "(list)"), (("", "cons"), "(cons _ _)")) if k not in full]
        elif t[0] == "N" and t[1] in self.prog.type_index and self.prog.type_index[t[1]].kind == "sum":
            ti = self.prog.type_index[t[1]]
            missing = [v for v in ti.variants if (ti.mod.name, v) not in full]
        elif t[0] == "M":
            self.diag(m, "E-TYPE", node, path, "cannot infer the type of the matched expression; bind it with a typed parameter first")
            return
        else:
            missing = ["_ (a catch-all pattern)"]
        if missing:
            self.diag(m, "E-MATCH-NONEXHAUSTIVE", node, path, "match is not exhaustive; missing: " + " ".join(missing), expected=" ".join(missing))
