"""Special forms: if let let? do match lam list new get with and or fail try note prim."""
from __future__ import annotations

from .facts import Binding
from .resolve import head
from .sexpr import Atom, SList
from .forms_for import ForFormsMixin
from .forms_match import MatchFormsMixin
from .printer import flat
from .types import (
    BOOL, FLOAT, INT, NEVER, STR, UNIT, fields_of, fn, lst, nom, opt,
    pair, var, vec,
)


class FormsMixin(MatchFormsMixin, ForFormsMixin):
    def _shape(self, m, e, path, usage):
        self.diag(m, "E-PARSE", e, path, f"expected {usage}")
        return self.s.fresh()

    # ---- control ---------------------------------------------------------------------------
    def f_if(self, m, e, env, path):
        it = e.items
        if not self.arity(m, "`if`", 3, len(it) - 1, e, path):
            self.infer_all(m, it[1:], env, path)
            return self.s.fresh()
        c = self.infer(m, it[1], env, path + "/1")
        self.expect(m, BOOL, c, it[1], path + "/1", "condition")
        saved_f = self.facts
        try:
            (tf := self.facts.fork()).add_condition(it[1], self.bindings, env, self.s, False)
            self.facts = tf
            a = self.infer(m, it[2], env, path + "/2")
            (ef := saved_f.fork()).add_condition(it[1], self.bindings, env, self.s, True)
            self.facts = ef
            b = self.infer(m, it[3], env, path + "/3")
        finally:
            self.facts = saved_f
        if self.s.walk(a)[0] == "Never":
            return b
        self.expect(m, a, b, it[3], path + "/3", "else-branch must match then-branch")
        return a

    def f_let(self, m, e, env, path):
        sb = dict(self.bindings)
        try:
            env2 = self._bindings(m, e, env, path, "let", lambda t, node, bp: t)
            return self.s.fresh() if env2 is None else self.infer(m, e.items[2], env2, path + "/2")
        finally:
            self.bindings = sb

    def f_let_q(self, m, e, env, path):
        """`(let? ((x e)..) body)`: each `e` is (Opt T) and binds its payload; body and form are (Opt R) (ADR-045)."""
        def payload(t, node, bp):
            a = self.s.fresh()
            self.expect(m, opt(a), t, node, bp, "binding in `let?` must be an Opt")
            return a
        sb = dict(self.bindings)
        try:
            env2 = self._bindings(m, e, env, path, "let?", payload)
            if env2 is None:
                return self.s.fresh()
            res = opt(self.s.fresh())
            self.expect(m, res, self.infer(m, e.items[2], env2, path + "/2"), e.items[2], path + "/2", "body of `let?` must be an Opt")
            return res
        finally:
            self.bindings = sb

    def _bindings(self, m, e, env, path, form, bound):
        """Sequential `((name expr)..)` of let/let?: returns the body's environment, or None if malformed."""
        it = e.items
        if len(it) != 3 or not isinstance(it[1], SList):
            self._shape(m, e, path, f"({form} ((name expr)...) body)")
            return None
        env2 = dict(env)
        for i, b in enumerate(it[1].items):
            bp = f"{path}/1/{i}"
            if not (isinstance(b, SList) and len(b.items) == 2 and isinstance(b.items[0], Atom) and b.items[0].kind == "sym"):
                self._shape(m, b, bp, "(name expr)")
                continue
            t = bound(self.infer(m, b.items[1], env2, bp + "/1"), b.items[1], bp + "/1")
            nm = b.items[0].value
            self.local_ok(m, nm, b.items[0], bp + "/0", env2)
            env2[nm] = t
            self.bindings[nm] = Binding(nm, id(b))
        return env2

    def f_do(self, m, e, env, path):
        it = e.items
        if len(it) < 2:
            return self._shape(m, e, path, "(do expr...)")
        ts = self.infer_all(m, it[1:], env, path)
        for i, t in enumerate(ts[:-1], 1):
            self.expect(m, UNIT, t, it[i], f"{path}/{i}", "step in `do`")
        return ts[-1]

    def f_and(self, m, e, env, path):
        it = e.items
        if len(it) < 3:
            self.diag(m, "E-ARITY", e, path, f"`{it[0].value}` expects at least 2 arguments", expected=">= 2", found=str(len(it) - 1))
        sf, cf, ts = self.facts, self.facts.fork(), []
        try:
            for i, a in enumerate(it[1:], 1):
                self.facts = cf.fork()
                ts.append(self.infer(m, a, env, f"{path}/{i}"))
                cf.add_condition(a, self.bindings, env, self.s, False)
        finally:
            self.facts = sf
        for i, t in enumerate(ts, 1):
            self.expect(m, BOOL, t, it[i], f"{path}/{i}", "operand")
        return BOOL

    def f_or(self, m, e, env, path):
        it = e.items
        ts = self.infer_all(m, it[1:], env, path)
        if len(it) < 3:
            self.diag(m, "E-ARITY", e, path, f"`{it[0].value}` expects at least 2 arguments", expected=">= 2", found=str(len(it) - 1))
        for i, t in enumerate(ts, 1):
            self.expect(m, BOOL, t, it[i], f"{path}/{i}", "operand")
        return BOOL

    def f_list(self, m, e, env, path):
        el = self.s.fresh()
        for i, t in enumerate(self.infer_all(m, e.items[1:], env, path), 1):
            self.expect(m, el, t, e.items[i], f"{path}/{i}", "list element")
        return lst(el)

    def f_vecof(self, m, e, env, path):
        el = self.s.fresh()
        for i, t in enumerate(self.infer_all(m, e.items[1:], env, path), 1):
            self.expect(m, el, t, e.items[i], f"{path}/{i}", "Vec element")
        return vec(el)

    def f_note(self, m, e, env, path):
        if not (len(e.items) == 2 and isinstance(e.items[1], Atom) and e.items[1].kind == "str"):
            return self._shape(m, e, path, '(note "text")')
        return UNIT

    def f_prim(self, m, e, env, path):
        if not m.is_stdlib:
            self.diag(m, "E-NAME-UNRESOLVED", e, path, "(prim ...) is reserved for stdlib modules")
        elif not (len(e.items) == 2 and isinstance(e.items[1], Atom) and e.items[1].kind == "str"):
            return self._shape(m, e, path, '(prim "name")')
        return self.s.fresh()

    def f_catch(self, m, e, env, path):
        return self._shape(m, e, path, "(catch ...) only inside (try ...)")

    # ---- lambda ------------------------------------------------------------------------------
    def f_lam(self, m, e, env, path):
        it = e.items
        if len(it) != 3 or not isinstance(it[1], SList):
            return self._shape(m, e, path, "(lam ((name Type)...) body)")
        has_typed = any(isinstance(p, SList) for p in it[1].items)
        has_untyped = any(isinstance(p, Atom) for p in it[1].items)
        if has_typed and has_untyped:
            self.diag(m, "E-PARSE", it[1], f"{path}/1", "cannot mix typed and untyped parameters in a lambda; all parameters must be typed or all untyped")
            return self.s.fresh()
        pts, penv = [], {}
        if has_typed:
            for i, p in enumerate(it[1].items):
                pp = f"{path}/1/{i}"
                if not (isinstance(p, SList) and len(p.items) == 2 and isinstance(p.items[0], Atom) and p.items[0].kind == "sym"):
                    return self._shape(m, p, pp, "(name Type)")
                nm = p.items[0].value
                self.local_ok(m, nm, p.items[0], pp + "/0", env, penv)
                penv[nm] = self.resolve_type(m, p.items[1], None, pp + "/1")
                pts.append(penv[nm])
        else:
            for i, p in enumerate(it[1].items):
                pp = f"{path}/1/{i}"
                if not (isinstance(p, Atom) and p.kind == "sym"):
                    return self._shape(m, p, pp, "parameter name")
                nm = p.value
                self.local_ok(m, nm, p, pp, env, penv)
                t = self.s.fresh()
                penv[nm] = t
                pts.append(t)
                self.__dict__.setdefault("untyped_params", []).append((m, nm, t, p, pp))
        sb = dict(self.bindings)
        try:
            for nm in penv:
                self.bindings[nm] = Binding(nm, f"lam:{id(e)}:{nm}")
            bt = self.sandbox(m, "a lambda", lambda: self.infer(m, it[2], {**env, **penv}, path + "/2"))
        finally:
            self.bindings = sb
        ft = fn(pts, bt)
        self.note_keys(ft, e, path)
        return ft


    # ---- records ---------------------------------------------------------------------------------
    def _rec(self, m, t, node, path):
        t = self.s.walk(t)
        ti = self.prog.type_index.get(t[1]) if t[0] == "N" else None
        if ti is None or ti.kind != "rec":
            self.diag(m, "E-TYPE", node, path, f"expected a record value, found {self.s.show(t)}", expected="record", found=self.s.show(t))
            return None
        return ti

    def _field_pairs(self, m, ti, rt, pairs, env, path, start, need_all):
        fields = dict(fields_of(ti, self.s.walk(rt)))
        seen = set()
        for i, p in enumerate(pairs, start):
            pp = f"{path}/{i}"
            if not (isinstance(p, SList) and len(p.items) == 2 and isinstance(p.items[0], Atom) and p.items[0].kind == "sym"):
                self._shape(m, p, pp, "(field expr)")
                continue
            fname = p.items[0].value
            t = self.infer(m, p.items[1], env, pp + "/1")
            if fname not in fields:
                self.diag(m, "E-TYPE", p.items[0], pp + "/0", f"type {ti.name} has no field `{fname}`", expected=" ".join(fields), found=fname)
            elif fname in seen:
                self.diag(m, "E-TYPE", p.items[0], pp + "/0", f"field `{fname}` given twice")
            else:
                self.expect(m, fields[fname], t, p.items[1], pp + "/1", f"field `{fname}`")
            seen.add(fname)
        return sorted(set(fields) - seen) if need_all else []

    def f_new(self, m, e, env, path):
        it = e.items
        if len(it) < 2 or not (isinstance(it[1], Atom) and it[1].kind == "type"):
            return self._shape(m, e, path, "(new Type (field expr)...)")
        hit = self.find_cap(m, it[1].value, ("type",), it[1], path + "/1")
        if hit is None:
            self.infer_all(m, [p.items[1] for p in it[2:] if isinstance(p, SList) and len(p.items) == 2], env, path)
            return self.s.fresh()
        ti = hit[1]
        self.prog.refs[(m.name, path + "/1")] = ti.qual
        if ti.kind != "rec":
            self.diag(m, "E-TYPE", it[1], path + "/1", f"`{it[1].value}` is not a record type")
            return self.s.fresh()
        rt = self.s.inst(nom(ti.qual, *(var(p) for p in ti.params)), {})
        self.note_keys(rt, e, path)
        missing = self._field_pairs(m, ti, rt, it[2:], env, path, 2, True)
        if missing:
            self.diag(m, "E-TYPE", e, path, "missing field(s): " + " ".join(missing), expected=" ".join(missing))
        return rt

    def f_with(self, m, e, env, path):
        it = e.items
        if len(it) < 3:
            return self._shape(m, e, path, "(with record (field expr)...)")
        rt = self.infer(m, it[1], env, path + "/1")
        ti = self._rec(m, rt, it[1], path + "/1")
        if ti is None:
            return self.s.fresh()
        self.note_keys(rt, e, path)
        self._field_pairs(m, ti, rt, it[2:], env, path, 2, False)
        return rt

    def f_get(self, m, e, env, path):
        it = e.items
        if not (len(it) == 3 and isinstance(it[2], Atom) and it[2].kind == "sym"):
            return self._shape(m, e, path, "(get record field)")
        rt = self.infer(m, it[1], env, path + "/1")
        ti = self._rec(m, rt, it[1], path + "/1")
        if ti is None:
            return self.s.fresh()
        self.note_keys(rt, e, path)
        fields = dict(fields_of(ti, self.s.walk(rt)))
        if it[2].value not in fields:
            self.diag(m, "E-TYPE", it[2], path + "/2", f"type {ti.name} has no field `{it[2].value}`", expected=" ".join(fields), found=it[2].value)
            return self.s.fresh()
        return fields[it[2].value]

    # ---- failures --------------------------------------------------------------------------------
    def fail_check(self, m, e, env, path):
        it = e.items
        if len(it) < 2 or not (isinstance(it[1], Atom) and it[1].kind == "type"):
            self._shape(m, e, path, "(fail ErrorName expr...)")
            return None
        hit = self.find_cap(m, it[1].value, ("error",), it[1], path + "/1")
        ats = self.infer_all(m, it[2:], env, path, 2)
        if hit is None:
            return None
        err = hit[1]
        self.prog.refs[(m.name, path + "/1")] = err.id
        if self.arity(m, f"error `{it[1].value}`", len(err.fields), len(ats), e, path):
            for i, ((fname, ft), got) in enumerate(zip(err.fields, ats), 2):
                self.expect(m, ft, got, it[i], f"{path}/{i}", f"field `{fname}`")
        return err

    def f_fail(self, m, e, env, path):
        err = self.fail_check(m, e, env, path)
        if err is not None:
            self.note_fail(err.id, path, e)
        return NEVER

    def f_try(self, m, e, env, path):
        it = e.items
        if len(it) < 3:
            return self._shape(m, e, path, "(try expr (catch Error (name...) handler)...)")
        self.frames.append({})
        res = self.infer(m, it[1], env, path + "/1")
        frame = self.frames.pop()
        for i, c in enumerate(it[2:], 2):
            cp = f"{path}/{i}"
            if not (head(c) == "catch" and len(c.items) == 4 and isinstance(c.items[1], Atom) and c.items[1].kind == "type" and isinstance(c.items[2], SList)):
                self._shape(m, c, cp, "(catch ErrorName (name...) handler)")
                continue
            hit = self.find_cap(m, c.items[1].value, ("error",), c.items[1], cp + "/1")
            binds: dict = {}
            if hit is not None:
                err = hit[1]
                self.prog.refs[(m.name, cp + "/1")] = err.id
                names = c.items[2].items
                if self.arity(m, f"catch `{c.items[1].value}`", len(err.fields), len(names), c, cp):
                    for nm, (_, ft) in zip(names, err.fields):
                        if isinstance(nm, Atom) and nm.kind == "sym":
                            self.local_ok(m, nm.value, nm, cp + "/2", env, binds)
                            binds[nm.value] = ft
                frame.pop(err.id, None)
            ht = self.infer(m, c.items[3], {**env, **binds}, cp + "/3")
            if self.s.walk(res)[0] == "Never":
                res = ht
            else:
                self.expect(m, res, ht, c.items[3], cp + "/3", "handler must match the protected expression")
        for fid, v in frame.items():
            self.frames[-1].setdefault(fid, v)
        return res
