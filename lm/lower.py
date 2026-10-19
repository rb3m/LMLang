"""Lowering: checked `Program` -> target-neutral IR (`ir.py`). Mirrors `interp.py` form by form.

Only functions reachable from the given roots are lowered, so an unused stdlib prim never blocks a
build. Input must be a program without check errors; anything unexpected is a toolchain bug.
"""
from __future__ import annotations

from . import ir
from .lower_consts import sort_consts
from .prelude import SPECIAL, VALUES, form_method
from .program import ConstInfo, FnInfo, ModInfo, Program
from .resolve import head
from .sexpr import Atom, SList
from .tailcall import tail_sites

INT_MIN, INT_MAX = -(2 ** 63), 2 ** 63 - 1


class LowerError(Exception):
    """A checked program the backend cannot represent (e.g. an Int literal outside 64 bits)."""


class Lowerer:
    def __init__(self, prog: Program):
        self.prog = prog
        self.out = ir.Program(stdlib={n for n, m in prog.modules.items() if m.is_stdlib})
        self.queue: list = []
        self.tail_sites = set()

    # ---- program ---------------------------------------------------------------------------
    def fn_info(self, fid: str) -> FnInfo:
        q, b = fid.split(".", 1)
        return self.prog.modules[q].fns[b]

    def const_info(self, cid: str) -> ConstInfo:
        q, b = cid.split(".", 1)
        return self.prog.modules[q].consts[b]

    def is_const(self, name: str, m: ModInfo) -> bool:
        if "." in name:
            q, b = name.split(".", 1)
            return q in self.prog.modules and b in self.prog.modules[q].consts
        return name in m.consts

    def need_const(self, cid: str) -> str:
        if cid not in self.out.consts:
            c = self.const_info(cid)
            val_expr = c.clauses["value"][0].items[1]
            base = f"{c.mod.name}/{c.name}"
            ir_expr = self.ex(val_expr, c.mod, set(), f"{base}/value/1", c.qual)
            self.out.consts[cid] = ir.Const(cid, ir_expr)
        return cid

    def need(self, fid: str) -> str:
        if fid not in self.out.fns and fid not in self.queue:
            self.queue.append(fid)
        return fid

    def drain(self):
        while self.queue:
            fid = self.queue.pop()
            if fid not in self.out.fns:
                self.out.fns[fid] = self.lower_fn(self.fn_info(fid))
        self.out.const_order = sort_consts(self.out)

    def lower_fn(self, f: FnInfo) -> ir.Fn:
        m, base = f.mod, f"{f.mod.name}/{f.name}"
        params = [p for p, _ in f.params]
        body = f.clauses["body"][0].items[1]
        fn = ir.Fn(f.qual, params, None, None)
        self.out.fns[f.qual] = fn  # placeholder first: recursion terminates
        if head(body) == "prim":
            fn.prim = body.items[1].value
            self.out.prims.add(fn.prim)
        else:
            self.tail_sites = tail_sites(body, f.name)
            fn.tail = bool(self.tail_sites)
            fn.body = self.ex(body, m, set(params), f"{base}/body/1", f.qual)
            self.tail_sites = set()  # contracts and example arguments never contain loop transfers
        for key, code, extra in (("requires", "E-REQUIRES-VIOLATED", set()), ("ensures", "E-ENSURES-VIOLATED", {"result"})):
            for k, c in enumerate(f.clauses.get(key, [])):
                p = f"{base}/{key}#{k}"
                e = self.ex(c.items[1], m, set(params) | extra, p + "/1", f.qual)
                getattr(fn, key).append(ir.Contract(e, ir.Site(m.file, c.line, c.col, p, f.qual), code))
        return fn

    # ---- names -------------------------------------------------------------------------------
    def vkey(self, name: str, m: ModInfo) -> str:
        """Constructor id, as interp.vkey: `mod.Name`, or bare for prelude variants."""
        if "." in name:
            return name
        if name in m.variants:
            return f"{m.name}.{name}"
        return name

    def ctor(self, name, m, nargs) -> str:
        c = self.vkey(name, m)
        if "." in c:
            self.out.ctors[c] = nargs
        return c

    def err_id(self, name, m) -> str:
        e = name if "." in name else (f"{m.name}.{name}" if name in m.errors else name)
        self.out.errors.add(e)
        return e

    def rtype(self, name, m) -> str:
        q = name if "." in name else f"{m.name}.{name}"
        self.out.records[q] = [fname for fname, _ in self.prog.type_index[q].fields]
        return q

    # ---- expressions ---------------------------------------------------------------------------
    def ex(self, e, m: ModInfo, env: set, path: str, fq: str):
        if isinstance(e, Atom):
            return self.atom(e, m, env)
        h = e.items[0]
        kids = e.items[1:]
        sub = lambda k: f"{path}/{k}"
        if isinstance(h, Atom) and h.kind == "sym" and h.value in SPECIAL:
            return getattr(self, form_method("s_", h.value))(e, m, env, path, fq)
        args = [self.ex(a, m, env, sub(k + 1), fq) for k, a in enumerate(kids)]
        if id(e) in self.tail_sites:
            return ir.TailCall(args)
        if isinstance(h, Atom) and h.kind == "type":
            return ir.Construct(self.ctor(h.value, m, len(args)), args)
        discharged = id(e) in self.prog.discharged
        if isinstance(h, Atom) and h.kind == "sym" and h.value not in env:
            if h.value in VALUES:
                return ir.PrimOp(h.value, args, ir.Site(m.file, e.line, e.col, path, fq), discharged=discharged)
            if self.is_const(h.value, m):
                return ir.Apply(self.ex(h, m, env, sub(0), fq), args)
            fid = self.need(self.global_fid(h.value, m))
            site = ir.Site(m.file, e.line, e.col, path, fq) if discharged else None
            return ir.Call(fid, args, site=site, discharged=discharged)
        return ir.Apply(self.ex(h, m, env, sub(0), fq), args)

    def global_fid(self, name, m) -> str:
        return name if "." in name else f"{m.name}.{name}"

    def atom(self, e: Atom, m, env):
        k, v = e.kind, e.value
        if k == "int":
            if not INT_MIN <= v <= INT_MAX:
                raise LowerError(f"{m.file}:{e.line}:{e.col}: integer literal {v} is outside the signed 64-bit range")
            return ir.Lit("int", v)
        if k == "float":
            return ir.Lit("float", v)
        if k == "str":
            return ir.Lit("str", v)
        if k == "type":
            return ir.Construct(self.ctor(v, m, 0), [])
        if v in ("true", "false"):
            return ir.Lit("bool", v == "true")
        if v == "unit":
            return ir.Lit("unit", None)
        if v in env:
            return ir.Local(v)
        if v in VALUES:
            return ir.PreludeRef(v)
        if self.is_const(v, m):
            cid = v if "." in v else f"{m.name}.{v}"
            return ir.ConstRef(self.need_const(cid))
        return ir.FnRef(self.need(self.global_fid(v, m)))

    def s_if(self, e, m, env, p, fq):
        c, a, b = (self.ex(x, m, env, f"{p}/{k}", fq) for k, x in ((1, e.items[1]), (2, e.items[2]), (3, e.items[3])))
        return ir.If(c, a, b)

    def _bindings(self, e, m, env, p, fq):
        """Lowered `((name expr)..)` of let/let? in order, and the body's environment."""
        binds, env2 = [], set(env)
        for k, b in enumerate(e.items[1].items):
            name = b.items[0].value
            binds.append((name, self.ex(b.items[1], m, env2, f"{p}/1/{k}/1", fq)))
            env2.add(name)
        return binds, self.ex(e.items[2], m, env2, f"{p}/2", fq)

    def s_let(self, e, m, env, p, fq):
        binds, out = self._bindings(e, m, env, p, fq)
        for name, val in reversed(binds):
            out = ir.Let(name, val, out)
        return out

    def s_let_q(self, e, m, env, p, fq):
        """Nested matches, innermost first: (match e1 ((Some x) <rest>) (_ None)) (ADR-045)."""
        binds, out = self._bindings(e, m, env, p, fq)
        for name, val in reversed(binds):
            some = ir.Arm([ir.Test((), "tag", "Some")], [(name, (("arg", 0),))], out)
            out = ir.Match(val, [some, ir.Arm([], [], ir.Construct("None", []))])
        return out

    def s_match(self, e, m, env, p, fq):
        subj = self.ex(e.items[1], m, env, f"{p}/1", fq)
        arms = []
        for k, arm in enumerate(e.items[2:]):
            tests, binds = [], []
            self.pattern(arm.items[0], (), m, tests, binds)
            body = self.ex(arm.items[1], m, env | {n for n, _ in binds}, f"{p}/{k + 2}/1", fq)
            arms.append(ir.Arm(tests, binds, body))
        return ir.Match(subj, arms)

    def pattern(self, pat, path, m, tests, binds):
        if isinstance(pat, Atom):
            if pat.kind == "int":
                tests.append(ir.Test(path, "int", pat.value))
            elif pat.kind == "str":
                tests.append(ir.Test(path, "str", pat.value))
            elif pat.kind == "type":
                tests.append(ir.Test(path, "tag", self.ctor(pat.value, m, 0)))
            elif pat.value in ("true", "false"):
                tests.append(ir.Test(path, "bool", pat.value == "true"))
            elif pat.value not in ("_", "unit"):
                binds.append((pat.value, path))
            return
        h, subs = pat.items[0].value, pat.items[1:]
        if h == "list":
            tests.append(ir.Test(path, "len", len(subs)))
            for k, sp in enumerate(subs):
                self.pattern(sp, path + (("elem", k),), m, tests, binds)
            return
        if h == "cons":
            tests.append(ir.Test(path, "nonempty", None))
            self.pattern(subs[0], path + (("elem", 0),), m, tests, binds)
            self.pattern(subs[1], path + (("tail",),), m, tests, binds)
            return
        if h == "pair":
            tests.append(ir.Test(path, "pair", None))
            self.pattern(subs[0], path + (("first",),), m, tests, binds)
            self.pattern(subs[1], path + (("second",),), m, tests, binds)
            return
        tests.append(ir.Test(path, "tag", self.ctor(h, m, len(subs))))
        for k, sp in enumerate(subs):
            self.pattern(sp, path + (("arg", k),), m, tests, binds)

    def s_lam(self, e, m, env, p, fq):
        params = [x.value if isinstance(x, Atom) else x.items[0].value for x in e.items[1].items]
        body = self.ex(e.items[2], m, env | set(params), f"{p}/2", fq)
        return ir.Lambda(params, sorted(ir.free_locals(body, frozenset(params))), body)

    def s_list(self, e, m, env, p, fq):
        return ir.ListLit([self.ex(a, m, env, f"{p}/{k + 1}", fq) for k, a in enumerate(e.items[1:])])

    def s_mapof(self, e, m, env, p, fq):
        pairs = e.items[1:]
        keys = [self.atom(x.items[0], m, env) for x in pairs]
        return ir.MapLit(keys, [self.ex(x.items[1], m, env, f"{p}/{k + 1}/1", fq) for k, x in enumerate(pairs)])

    def s_setof(self, e, m, env, p, fq):
        return ir.SetLit([self.atom(x, m, env) for x in e.items[1:]])

    def _pairs(self, items, start, m, env, p, fq):
        return [(x.items[0].value, self.ex(x.items[1], m, env, f"{p}/{k + start}/1", fq)) for k, x in enumerate(items)]

    def s_new(self, e, m, env, p, fq):
        return ir.NewRec(self.rtype(e.items[1].value, m), self._pairs(e.items[2:], 2, m, env, p, fq))

    def s_get(self, e, m, env, p, fq):
        return ir.GetField(self.ex(e.items[1], m, env, f"{p}/1", fq), e.items[2].value)

    def s_with(self, e, m, env, p, fq):
        return ir.With(self.ex(e.items[1], m, env, f"{p}/1", fq), self._pairs(e.items[2:], 2, m, env, p, fq))

    def s_and(self, e, m, env, p, fq):
        return ir.And([self.ex(a, m, env, f"{p}/{k + 1}", fq) for k, a in enumerate(e.items[1:])])

    def s_or(self, e, m, env, p, fq):
        return ir.Or([self.ex(a, m, env, f"{p}/{k + 1}", fq) for k, a in enumerate(e.items[1:])])

    def s_do(self, e, m, env, p, fq):
        return ir.Do([self.ex(a, m, env, f"{p}/{k + 1}", fq) for k, a in enumerate(e.items[1:])])

    def s_for(self, e, m, env, p, fq):
        name = e.items[1].items[0].value
        xs = self.ex(e.items[1].items[1], m, env, f"{p}/1/1", fq)
        body = self.ex(e.items[2], m, env | {name}, f"{p}/2", fq)
        return ir.For(name, xs, body)

    def s_note(self, e, m, env, p, fq):
        return ir.Lit("unit", None)

    def s_fail(self, e, m, env, p, fq):
        args = [self.ex(a, m, env, f"{p}/{k + 2}", fq) for k, a in enumerate(e.items[2:])]
        return ir.Fail(self.err_id(e.items[1].value, m), args)

    def s_try(self, e, m, env, p, fq):
        body = self.ex(e.items[1], m, env, f"{p}/1", fq)
        hs = []
        for k, c in enumerate(e.items[2:]):
            names = [a.value for a in c.items[2].items]
            hs.append(ir.Handler(self.err_id(c.items[1].value, m), names,
                                 self.ex(c.items[3], m, env | set(names), f"{p}/{k + 2}/3", fq)))
        return ir.Try(body, hs)

    def s_prim(self, e, m, env, p, fq):
        raise LowerError("(prim ...) is only valid as a whole fn body")

    s_catch = s_prim


def lower(prog: Program, roots) -> ir.Program:
    """Lower the functions reachable from `roots` (qualified fn ids)."""
    lo = Lowerer(prog)
    for r in roots:
        lo.need(r)
    lo.drain()
    return lo.out


def lower_examples(prog: Program, modules):
    """IR program plus one case per example: [(label, fid, [arg IR])], label = `mod/fn/example#k`."""
    lo = Lowerer(prog)
    cases = []
    for mn in modules:
        m = prog.modules[mn]
        for name in sorted(m.fns):
            f = m.fns[name]
            for k, c in enumerate(f.clauses.get("example", [])):
                p = f"{mn}/{name}/example#{k}"
                args = [lo.ex(a, m, set(), f"{p}/1/{i}", f.qual) for i, a in enumerate(c.items[1].items)]
                cases.append((p, lo.need(f.qual), args))
    from .runtime_cases import fixture_cases
    for label, f, _ in fixture_cases(prog, modules):
        cases.append((label, lo.need(f.qual), []))
    lo.drain()
    return lo.out, cases
