"""Function-level checking: contracts, examples, effects, failures; calls and names."""
from __future__ import annotations

import math

from .check_types import TypeChecksMixin
from .check_pat import discharged_compile
from .consts import check_const, check_const_cycles, eval_all_consts
from .examples import check_example
from .facts import Binding, FactSet, LenTerm, extract_term
from .forms import FormsMixin
from .forms_coll import CollFormsMixin
from .prelude import CONSTRAINED, FAILING, RESERVED_VALUES, SPECIAL, VALUES, form_method
from .resolve import Resolver, head, suggest
from .sexpr import Atom, SList
from .types import BOOL, FLOAT, INT, STR, UNIT, fn
from .values import INT_MAX, INT_MIN, in_range


class Checker(TypeChecksMixin, CollFormsMixin, FormsMixin, Resolver):
    cur_mod = cur_fn = None
    check_all = False  # also check non-target modules (diagnostics stay suppressed); used by queries
    facts: FactSet | None = None
    bindings: dict | None = None

    def clear_facts(self):
        """Start a context with no bindings and no facts (outside any fn: consts, external values)."""
        self.bindings, self.facts = {}, FactSet()

    # ---- driver --------------------------------------------------------------------------
    def run(self):
        self.clear_facts()
        self.build()
        from .deps import check_effects
        check_effects(self.prog)
        for n in sorted(self.prog.modules):
            m = self.prog.modules[n]
            if m.report or self.check_all:
                self.check_module(m)
        check_const_cycles(self.prog, self)
        eval_all_consts(self.prog, self)
        self.check_examples()
        for m in self.prog.modules.values():
            if m.report or self.check_all:
                self.check_uses(m)

    def check_module(self, m):
        for u in m.uses:
            if u.value not in self.prog.available:
                self.diag(m, "E-NAME-UNRESOLVED", u, f"{m.name}/use", f"no module named `{u.value}`", expected=" ".join(suggest(u.value, self.prog.available)), found=u.value)
        for nm in sorted(m.consts):
            check_const(self, m, m.consts[nm])
        for nm in sorted(m.fns):
            self.check_fn(m, m.fns[nm])

    def check_uses(self, m):
        for u in m.uses:
            if u.value in self.prog.modules and u.value not in m.used:
                self.diag(m, "W-USE-UNUSED", u, f"{m.name}/use", f"module `{u.value}` is in (use ...) but never referenced",
                          fix=[{"op": "remove-use", "module": m.name, "use": u.value}])

    def check_examples(self):
        for n in sorted(self.prog.modules):
            m = self.prog.modules[n]
            if not (m.is_target or self.check_all):
                continue
            for f in m.fns.values():
                if not f.sig_ok:
                    continue
                self.cur_mod, self.cur_fn = m, f
                self.clear_facts()
                self.eq_checks = []
                for k, c in enumerate(f.clauses.get("example", [])):
                    check_example(self, m, f, c,
                                  f"{m.name}/{f.name}/example#{k}")
                self.check_eq(m)
        for n in sorted(self.prog.modules):
            m = self.prog.modules[n]
            if not (m.is_target or self.check_all):
                continue
            for fn_name in sorted(m.fns):
                f = m.fns[fn_name]
                if f.eff or "example" in f.clauses or not f.sig_ok:
                    continue
                # Pat has no constant representation, including in examples.
                # Exercise opaque signatures through concrete caller wrappers.
                if self.has_pat(fn([t for _, t in f.params], f.ret), set()):
                    continue
                needs = (fn_name in m.exported_fns) if m.export_nodes is not None else (fn_name in m.referenced_fns)
                if needs:
                    self.diag(m, "E-EXAMPLE-MISSING", f.node, f"{m.name}/{f.name}", f"exported fn `{f.name}` needs at least one (example ...)")

    # ---- accumulators ----------------------------------------------------------------------
    def note_eff(self, eff, path, node):
        self.effs.setdefault(eff, (path, node))

    def note_fail(self, fid, path, node):
        self.frames[-1].setdefault(fid, (path, node))

    def sandbox(self, m, what, run):
        saved = (getattr(self, "effs", {}), getattr(self, "frames", [{}]))
        self.effs, self.frames = {}, [{}]
        try:
            r = run()
        finally:
            effs, frames = self.effs, self.frames
            self.effs, self.frames = saved
        for e, (p, n) in effs.items():
            self.diag(m, "E-EFFECT-UNDECLARED", n, p, f"{what} must be pure but uses effect `{e}`", found=e)
        for e, (p, n) in frames[0].items():
            self.diag(m, "E-FAILS-UNDECLARED", n, p, f"{what} must be total but can fail with `{e}`", found=e)
        return r

    def expect(self, m, want, got, node, path, what=""):
        if not self.s.unify(want, got):
            w, g = self.s.show(want), self.s.show(got)
            self.diag(m, "E-TYPE", node, path, f"{what + ': ' if what else ''}expected {w}, found {g}", expected=w, found=g)
            return False
        return True

    def arity(self, m, name, want, got, node, path):
        if want != got:
            self.diag(m, "E-ARITY", node, path, f"{name} expects {want} argument(s), found {got}", expected=str(want), found=str(got))
            return False
        return True

    def local_ok(self, m, name, node, path, env, extra=None):
        if name in RESERVED_VALUES or name in m.fns or name in m.consts or name in env or (extra is not None and name in extra):
            self.diag(m, "E-DUP-NAME", node, path, self._local_collision(m, name, env))
            return False
        return True

    def infer_all(self, m, nodes, env, path, start=1):
        return [self.infer(m, a, env, f"{path}/{i}") for i, a in enumerate(nodes, start)]

    # ---- functions ---------------------------------------------------------------------------
    def check_fn(self, m, f):
        if not f.sig_ok or "body" not in f.clauses or len(f.clauses["body"][0].items) != 2:
            return
        fp = f"{m.name}/{f.name}"
        self.cur_mod, self.cur_fn = m, f
        self.effs, self.frames, self.eq_checks = {}, [{}], []
        env = dict(f.params)
        self.bindings = {p: Binding(p, f"{f.qual}:{p}") for p, _ in f.params}
        self.facts = FactSet()
        for k, c in enumerate(f.clauses.get("requires", [])):
            self.contract(m, c, env, f"{fp}/requires#{k}")
        for k, c in enumerate(f.clauses.get("ensures", [])):
            self.contract(m, c, {**env, "result": f.ret}, f"{fp}/ensures#{k}")
        self.effs, self.frames = {}, [{}]
        init_f = FactSet()
        for c in f.clauses.get("requires", []):
            init_f.add_condition(c.items[1], self.bindings, env, self.s, False)
        self.facts = init_f
        body = f.clauses["body"][0].items[1]
        bt = self.infer(m, body, env, f"{fp}/body/1")
        self.expect(m, f.ret, bt, body, f"{fp}/body/1", "body")
        is_prim = head(body) == "prim"
        for e, (p, n) in self.effs.items():
            if e not in f.eff:
                self.diag(m, "E-EFFECT-UNDECLARED", n, p, f"effect `{e}` is not declared in fn `{f.name}`", expected=f"(eff ... {e})", found=e,
                          fix=[{"op": "add-eff", "fn": f.qual, "eff": e}], near=f.node)
        for fid, (p, n) in self.frames[0].items():
            if fid not in f.fails:
                self.diag(m, "E-FAILS-UNDECLARED", n, p, f"failure `{fid}` can escape fn `{f.name}` but is not declared", expected=f"(fails ... {fid})", found=fid,
                          fix=[{"op": "add-fails", "fn": f.qual, "error": fid}], near=f.node)
        if not is_prim:
            for e in sorted(f.eff - set(self.effs)):
                self.diag(m, "W-EFFECT-UNUSED", f.clauses["eff"][0], f"{fp}/eff", f"effect `{e}` is declared but never used")
            for fid in sorted(f.fails - set(self.frames[0])):
                self.diag(m, "W-FAILS-UNUSED", f.clauses["fails"][0], f"{fp}/fails", f"failure `{fid}` is declared but cannot occur")
        self.check_eq(m)

    def contract(self, m, c, env, path):
        if len(c.items) != 2:
            self.diag(m, "E-PARSE", c, path, f"({c.items[0].value} expr) takes exactly one expression")
            return
        def run():
            sf = self.facts
            self.facts = FactSet()
            try:
                t = self.infer(m, c.items[1], env, path + "/1")
                self.expect(m, BOOL, t, c.items[1], path + "/1", "contract")
            finally:
                self.facts = sf
        self.sandbox(m, "a contract", run)

    # ---- expressions: atoms and calls -----------------------------------------------------------
    def infer(self, m, e, env, path):
        if isinstance(e, Atom):
            return self.atom(m, e, env, path)
        if not e.items:
            self.diag(m, "E-PARSE", e, path, "empty expression `()`")
            return self.s.fresh()
        h = e.items[0]
        if isinstance(h, Atom) and h.kind == "sym" and h.value in SPECIAL:
            return getattr(self, form_method("f_", h.value))(m, e, env, path)
        return self.call(m, e, env, path)

    def atom(self, m, e, env, path):
        k, v = e.kind, e.value
        if k == "int":
            self.int_range(m, e, path)
            return INT
        if k == "float":
            self.float_range(m, e, path)
            return FLOAT
        if k == "str":
            return STR
        if k == "type":
            hit = self.find_cap(m, v, ("variant",), e, path)
            if hit is None:
                return self.s.fresh()
            vi = hit[1]
            self.prog.refs[(m.name, path)] = f"{vi.mod.name}.{vi.name}" if vi.mod.name else vi.name
            return self.variant_type(m, vi, e, path, callable_value=True)
        if v in ("true", "false"):
            return BOOL
        if v == "unit":
            return UNIT
        if v == "_":
            self.diag(m, "E-NAME-UNRESOLVED", e, path, "`_` is only valid in patterns")
            return self.s.fresh()
        if v in env:
            return env[v]
        if v in SPECIAL:
            self.diag(m, "E-PARSE", e, path, f"`{v}` is a special form; write ({v} ...)")
            return self.s.fresh()
        if v in m.consts:
            ci = m.consts[v]
            self.prog.refs[(m.name, path)] = ci.qual
            return ci.declared_type if ci.declared_type is not None else self.s.fresh()
        if "." in v:
            q, base = v.split(".", 1)
            m2 = self.find_module(m, q, e, path)
            if m2 is not None and base in m2.consts:
                if base not in m2.exported_consts:
                    self.diag(m, "E-NOT-EXPORTED", e, path, f"`{v}` exists but module `{q}` does not export it", found=v)
                    return self.s.fresh()
                ci = m2.consts[base]
                self.prog.refs[(m.name, path)] = ci.qual
                return ci.declared_type if ci.declared_type is not None else self.s.fresh()
        r = self.resolve_callee(m, e, env, path)
        if r is None:
            return self.s.fresh()
        ft, info, pname = r
        if info is not None:
            self.edge(info)
            if info.eff:
                self.diag(m, "E-EFFECT-UNDECLARED", e, path, f"`{v}` has effects and cannot be used as a value", found=",".join(sorted(info.eff)))
            if info.fails:
                self.diag(m, "E-FAILS-UNDECLARED", e, path, f"`{v}` can fail and cannot be used as a value", found=",".join(sorted(info.fails)))
        elif pname in FAILING:
            self.diag(m, "E-FAILS-UNDECLARED", e, path, f"`{v}` can fail and cannot be used as a value", found=FAILING[pname])
        elif pname in ("=", "!="):
            self.note_eq(ft[1][0], e, path)
        return ft

    def int_range(self, m, e, path):
        if not in_range(e.value):
            self.diag(m, "E-OVERFLOW", e, path, f"Int literal {e.value} is outside [{INT_MIN}, {INT_MAX}] (signed 64-bit)",
                      expected=f"[{INT_MIN}, {INT_MAX}]", found=str(e.value))

    def float_range(self, m, e, path):
        if not math.isfinite(e.value):
            self.diag(m, "E-FLOAT", e, path, f"Float literal {e.raw} is not finite in binary64 (largest: 1.7976931348623157e+308)",
                      expected="a finite binary64 value", found=e.raw)

    def edge(self, info):
        if self.cur_fn is not None:
            self.prog.calls.setdefault(self.cur_fn.qual, set()).add(info.qual)

    def resolve_callee(self, m, e, env, path):
        """-> (instantiated fn type, FnInfo | None, prelude name | None) or None (diagnosed)."""
        v = e.value
        if v in VALUES:
            self.prog.refs[(m.name, path)] = "prelude." + v
            ft = self.s.inst(VALUES[v], {})
            if v in CONSTRAINED:
                self.note_constraint(v, ft[1][0], e, path)
            return ft, None, v
        f = None
        if "." in v:
            f = self.find_fn(m, v, e, path)
            if f is None:
                return None
        elif v in m.fns:
            f = m.fns[v]
        if f is not None:
            if not f.sig_ok:
                return None
            self.prog.refs[(m.name, path)] = f.qual
            ft = self.fn_type(f)
            self.note_keys(ft, e, path)
            return ft, f, None
        if getattr(self, "in_for", 0) and v in ("break", "continue", "return"):
            self.diag(m, "E-NAME-UNRESOLVED", e, path, f"`{v}`: LM has no early exit (use a recursive function or `list.fold`)", found=v)
            return None
        cands = list(env) + list(m.fns) + list(m.consts) + list(VALUES) + [f"{u.value}.{n}" for u in m.uses if u.value in self.prog.modules for n in (list(self.prog.modules[u.value].exported_fns) + list(self.prog.modules[u.value].exported_consts))]
        near = suggest(v, cands)
        self.diag(m, "E-NAME-UNRESOLVED", e, path, f"unknown name `{v}`", expected=" ".join(near or sorted(set(cands))[:8]), found=v,
                  fix=[{"op": "replace-ref", "path": path, "to": near[0]}] if near else [])
        return None

    def call(self, m, e, env, path):
        h, args = e.items[0], e.items[1:]
        hp = path + "/0"
        if isinstance(h, Atom) and h.kind == "type":
            return self.construct(m, e, env, path)
        info = pname = None
        if isinstance(h, Atom) and h.kind == "sym":
            if h.value in env:
                ft = env[h.value]
            elif h.value in m.consts or ("." in h.value and (lambda q, b: (m2 := self.prog.modules.get(q)) and b in m2.consts)(*h.value.split(".", 1))):
                ft = self.atom(m, h, env, hp)
            else:
                r = self.resolve_callee(m, h, env, hp)
                if r is None:
                    self.infer_all(m, args, env, path)
                    return self.s.fresh()
                ft, info, pname = r
        elif isinstance(h, Atom):
            self.diag(m, "E-TYPE", h, hp, "a literal cannot be called")
            self.infer_all(m, args, env, path)
            return self.s.fresh()
        else:
            ft = self.infer(m, h, env, hp)
        name = h.value if isinstance(h, Atom) else "expression"
        ft = self.s.walk(ft)
        if ft[0] != "Fn":
            self.diag(m, "E-TYPE", h, hp, f"`{name}` is not callable (type {self.s.show(ft)})", found=self.s.show(ft))
            self.infer_all(m, args, env, path)
            return self.s.fresh()
        ats = self.infer_all(m, args, env, path)
        if self.arity(m, f"`{name}`", len(ft[1]), len(args), e, path):
            for i, (want, got) in enumerate(zip(ft[1], ats), 1):
                self.expect(m, want, got, args[i - 1], f"{path}/{i}", f"argument {i} of `{name}`")
        if pname in ("=", "!=") and ats:
            self.note_eq(ats[0], e, path)
        if pname in FAILING and not self.cannot_fail(pname, args, ats, e, path, env):
            self.note_fail(FAILING[pname], path, e)
        if info is not None:
            self.edge(info)
            for eff in info.eff:
                self.note_eff(eff, path, e)
            for fid in info.fails:
                if fid == "pat.BadPattern" and discharged_compile(self, info, args, e, path):
                    continue
                if fid == "OutOfRange" and self.discharged_nth(info, args, e, path):
                    continue
                self.note_fail(fid, path, e)
        return ft[2]

    def cannot_fail(self, pname, args, ats, e, path, env):
        """Int `/` and `mod` fail DivZero unless the divisor is a nonzero Int literal or proven nonzero;
        Float `/` never fails (dividing by zero is the fault E-FLOAT). An operand type not yet known counts as Int."""
        if len(args) != 2:
            return True
        if isinstance(args[1], Atom) and args[1].kind == "int" and args[1].value != 0:
            return True
        if pname == "/" and any(self.s.walk(t) == FLOAT for t in ats):
            return True
        term = extract_term(args[1], self.bindings, env, self.s)
        if term is not None and self.facts.is_nonzero(term):
            fq = self.cur_fn.qual if self.cur_fn else ""
            self.prog.discharged[id(e)] = (self.cur_mod.file if self.cur_mod else "", e.line, e.col, path, fq)
            return True
        return False

    def discharged_nth(self, info, args, e, path):
        operation = (info.mod.name, info.name)
        arity = {("list", "nth"): 2, ("vec", "nth"): 2,
                 ("vec", "put"): 3}.get(operation)
        if arity is None or len(args) != arity:
            return False
        k_node = args[1]
        if not (isinstance(k_node, Atom) and k_node.kind == "int" and k_node.value >= 0):
            return False
        b = self.bindings.get(args[0].value) if isinstance(args[0], Atom) and args[0].kind == "sym" else None
        if b is None:
            return False
        size_op = "vec.size" if info.mod.name == "vec" else "len"
        if self.facts.is_gt(LenTerm(b, size_op), k_node.value):
            fq = self.cur_fn.qual if self.cur_fn else ""
            self.prog.discharged[id(e)] = (self.cur_mod.file if self.cur_mod else "", e.line, e.col, path, fq)
            return True
        return False

    def construct(self, m, e, env, path):
        h, args = e.items[0], e.items[1:]
        hit = self.find_cap(m, h.value, ("variant",), h, path + "/0")
        ats = self.infer_all(m, args, env, path)
        if hit is None:
            return self.s.fresh()
        vi, mp = hit[1], {}
        self.prog.refs[(m.name, path + "/0")] = f"{vi.mod.name}.{vi.name}" if vi.mod.name else vi.name
        vt = self.s.inst(vi.vtype, mp)
        self.note_keys(vt, e, path)
        if self.arity(m, f"variant `{h.value}`", len(vi.fields), len(args), e, path):
            for i, ((fname, ft), got) in enumerate(zip(vi.fields, ats), 1):
                self.expect(m, self.s.inst(ft, mp), got, args[i - 1], f"{path}/{i}", f"field `{fname}`")
        return vt
