"""Go expression emitters mixed into gobackend.GoGen."""
from __future__ import annotations

import struct

from . import ir
from .gobackend_names import golit, local, mangle
from .printer import float_text

ARITH = {"+": "add", "-": "sub", "*": "mul", "/": "div", "mod": "mod"}
COMPARE = {"=": "equal({0}, {1})", "!=": "!equal({0}, {1})", "<": "less({0}, {1})", "<=": "!less({1}, {0})",
           ">": "less({1}, {0})", ">=": "!less({0}, {1})"}


class GoExprMixin:
    def x_Lit(self, e):
        if e.kind == "int":
            return f"Value(int64({e.value}))"
        if e.kind == "float":  # exact bits, with the canonical text for readers
            return f"fbits(0x{struct.unpack('<Q', struct.pack('<d', e.value))[0]:016x}) /* {float_text(e.value)} */"
        if e.kind == "str":
            return f"Value({golit(e.value)})"
        if e.kind == "bool":
            return "Value(true)" if e.value else "Value(false)"
        return "U"

    def x_Local(self, e):
        return local(e.name)

    def x_ConstRef(self, e):
        return mangle(e.cid, "K_")

    def x_FnRef(self, e):
        f, k = mangle(e.fid, "F_"), len(self.prog.fns[e.fid].params)
        if k in (1, 2):
            return f"Value(&Closure{{F{k}: {f}}})"
        call = ", ".join(f"a[{i}]" for i in range(k))
        return f"Value(&Closure{{FN: func(a []Value) Value {{ return {f}({call}) }}}})"

    def x_PreludeRef(self, e):
        return f"preludeValues[{golit(e.op)}]"

    def x_Call(self, e):
        if e.discharged and e.fid in ("list.nth", "vec.nth", "vec.put", "pat.compile"):
            a = self.args(e.args)
            fn = e.fid.replace(".", "_")
            return f"safe_{fn}({', '.join(a)}, {self.site(e.site)})"
        return f"{mangle(e.fid, 'F_')}({', '.join(self.args(e.args))})"

    def x_TailCall(self, e):
        # Always materialize each argument in written order, before replacing slots.
        temps = []
        for arg in e.args:
            t = self.tmp()
            self.emit(f"{t} := Value({self.expr(arg)})")
            temps.append(t)
        for k, t in enumerate(temps):
            self.emit(f"next{k} = {t}")
        self.emit("continue")
        return "U"  # unreachable expression assignment keeps parent emitters uniform

    def x_PrimOp(self, e):
        a = self.args(e.args)
        if e.op in ARITH:
            fn = ("safe_" + ARITH[e.op]) if (e.discharged and e.op in ("/", "mod")) else ARITH[e.op]
            return f"{fn}({a[0]}, {a[1]}, {self.site(e.site)})"
        if e.op in COMPARE:  # some templates swap operands: evaluate both first, in source order
            a = [self.spill(x) for x in a]
            return "Value(" + COMPARE[e.op].format(*a) + ")"
        if e.op == "not":
            return f"Value(!{a[0]}.(bool))"
        if e.op == "len":
            return f"Value(int64(len({a[0]}.([]Value))))"
        if e.op == "pair":
            return f"makePair({a[0]}, {a[1]})"
        return f"cons({a[0]}, {a[1]})"

    def x_Apply(self, e):
        f, *a = self.args([e.fn, *e.args])
        if len(a) in (1, 2):
            return f"call{len(a)}({f}, {', '.join(a)})"
        return f"callN({', '.join([f, *a])})"

    def x_If(self, e):
        c = self.expr(e.cond)
        t = self.tmp()
        self.emit(f"var {t} Value")
        self.block(f"if {c}.(bool) {{", lambda: self.assign(t, e.then), "} else {")
        self.ind += 1
        self.assign(t, e.else_)
        self.ind -= 1
        self.emit("}")
        return t

    def x_Let(self, e):
        t = self.tmp()
        self.emit(f"var {t} Value")

        def body():
            v = local(e.name)
            self.emit(f"{v} := Value({self.expr(e.value)})")
            self.emit(f"_ = {v}")
            self.assign(t, e.body)
        self.block("{", body)
        return t

    def path(self, subj: str, path) -> str:
        for step in path:
            if step[0] == "arg":
                subj = f"variantArg({subj}, {step[1]})"
            elif step[0] == "elem":
                subj = f"{subj}.([]Value)[{step[1]}]"
            elif step[0] == "tail":
                subj = f"Value({subj}.([]Value)[1:])"
            elif step[0] == "first":
                subj = f"{subj}.(*Pair).A"
            elif step[0] == "second":
                subj = f"{subj}.(*Pair).B"
        return subj

    def test(self, subj: str, t: ir.Test) -> str:
        p = self.path(subj, t.path)
        if t.kind == "pair":
            return f"isPair({p})"
        if t.kind == "tag":
            return f"hasTag({p}, {self.ctor(t.value)})"
        if t.kind == "int":
            return f"{p}.(int64) == {t.value}"
        if t.kind == "str":
            return f"{p}.(string) == {golit(t.value)}"
        if t.kind == "len":
            return f"len({p}.([]Value)) == {t.value}"
        if t.kind == "nonempty":
            return f"len({p}.([]Value)) > 0"
        return f"{p}.(bool)" if t.value else f"!{p}.(bool)"

    def ctor(self, c: str) -> str:
        return mangle(c, "C_")

    def x_Match(self, e):
        s = self.spill(self.expr(e.subject))
        self.emit(f"_ = {s}")
        t = self.tmp()
        self.emit(f"var {t} Value")
        for k, arm in enumerate(e.arms):
            cond = " && ".join(self.test(s, x) for x in arm.tests) or "true"
            self.emit(("if " if k == 0 else "} else if ") + cond + " {")
            self.ind += 1
            for name, p in arm.binds:
                self.emit(f"{local(name)} := {self.path(s, p)}")
                self.emit(f"_ = {local(name)}")
            self.assign(t, arm.body)
            self.ind -= 1
        self.emit("} else {")
        self.emit('\tpanic("lm: non-exhaustive match (checker bug)")')
        self.emit("}")
        return t

    def x_Lambda(self, e):
        """Lifted to a named top-level function `L<n>_<owner>` (captures first, then params), so a
        fault can name `(lam) in owner` from the Go call stack; the closure only forwards to it."""
        self.lam_n += 1
        name = f"L{self.lam_n}_{mangle(self.owner, '')}"
        caps, ps = [local(c) for c in e.captures], [local(p) for p in e.params]
        saved = (self.lines, self.ind)
        self.lines, self.ind = [], 0

        def body():
            self.emit(f"return {self.expr(e.body)}")
        self.block(f"func {name}({', '.join(x + ' Value' for x in caps + ps)}) Value {{", body)
        self.emit("")
        self.lifted += self.lines
        self.lines, self.ind = saved
        k = len(ps)
        if k in (1, 2):
            fwd = ", ".join(caps + ps)
            return f"Value(&Closure{{F{k}: func({', '.join(p + ' Value' for p in ps)}) Value {{ return {name}({fwd}) }}}})"
        fwd = ", ".join(caps + [f"a[{i}]" for i in range(k)])
        return f"Value(&Closure{{FN: func(a []Value) Value {{ return {name}({fwd}) }}}})"

    def x_Do(self, e):
        if not e.items:
            return "U"
        for x in e.items[:-1]:
            self.emit(f"_ = {self.expr(x)}")
        return self.expr(e.items[-1])

    def x_For(self, e):
        xs = self.spill(self.expr(e.list))
        v = local(e.name)
        elem = self.tmp()

        def body():
            self.emit(f"{v} := {elem}")
            self.emit(f"_ = {v}")
            self.emit(f"_ = {self.expr(e.body)}")

        self.block(f"for _, {elem} := range {xs}.([]Value) {{", body)
        return "U"

    def x_ListLit(self, e):
        return f"Value([]Value{{{', '.join(self.args(e.items))}}})"

    def x_VecLit(self, e):
        return f"vecOf([]Value{{{', '.join(self.args(e.items))}}})"

    def x_MapLit(self, e):
        keys = ", ".join(self.expr(k) for k in e.keys)  # literals: no statements
        return f"mapOf([]Value{{{keys}}}, []Value{{{', '.join(self.args(e.items))}}})"

    def x_SetLit(self, e):
        return f"setOf([]Value{{{', '.join(self.expr(k) for k in e.items)}}})"

    def x_Construct(self, e):
        if not e.args:
            return "Value(V_None)" if e.ctor == "None" else mangle(e.ctor, "N_")
        a = self.args(e.args)
        if e.ctor == "Some":
            return f"mkSome({a[0]})"
        return f"Value(&Variant{{{self.ctor(e.ctor)}, []Value{{{', '.join(a)}}}}})"

    def x_NewRec(self, e):
        vals = {f: self.spill(s) for (f, _), s in zip(e.fields, self.args([x for _, x in e.fields]))}
        order = self.prog.records[e.rtype]
        return f"Value(&Record{{{mangle(e.rtype, 'R_')}, []Value{{{', '.join(vals[f] for f in order)}}}}})"

    def x_GetField(self, e):
        return f"getField({self.expr(e.rec)}, {golit(e.field)})"

    def x_With(self, e):
        a = self.args([e.rec, *(x for _, x in e.updates)])
        pairs = "".join(f", {golit(f)}, {v}" for (f, _), v in zip(e.updates, a[1:]))
        return f"withFields({a[0]}{pairs})"

    def _andor(self, items, neg: str, empty: str):
        if not items:
            return empty
        t = self.tmp()
        self.emit(f"{t} := Value({self.expr(items[0])})")
        opened = 0
        for x in items[1:]:
            self.emit(f"if {neg}{t}.(bool) {{")
            self.ind += 1
            opened += 1
            self.assign(t, x)
        for _ in range(opened):
            self.ind -= 1
            self.emit("}")
        return t

    def x_And(self, e):
        return self._andor(e.items, "", "Value(true)")

    def x_Or(self, e):
        return self._andor(e.items, "!", "Value(false)")

    def x_Fail(self, e):
        return f"lmFail({', '.join([golit(e.err), *self.args(e.args)])})"

    def x_Try(self, e):
        r, f, d, x = self.tmp(), self.tmp(), self.tmp(), self.tmp()
        ids = " || ".join(f"{x}.ID == {golit(h.err)}" for h in e.handlers) or "false"
        self.emit(f"var {r} Value")
        self.emit(f"{d} := depth")

        def body():
            self.emit("defer func() {")
            self.emit(f"\tif p := recover(); p != nil {{")
            self.emit(f"\t\tif {x}, ok := p.(*Fail); ok && ({ids}) {{")
            self.emit(f"\t\t\tdepth, fl = {d}, {x}")
            self.emit("\t\t\treturn")
            self.emit("\t\t}")
            self.emit("\t\tpanic(p)")
            self.emit("\t}")
            self.emit("}()")
            self.assign(r, e.body)
            self.emit("return nil")
        self.block(f"{f} := func() (fl *Fail) {{", body, "}()")
        self.emit(f"if {f} != nil {{")
        self.ind += 1
        for k, h in enumerate(e.handlers):  # first handler with the failure's id wins, as in interp
            self.emit(("if " if k == 0 else "} else if ") + f"{f}.ID == {golit(h.err)} {{")
            self.ind += 1
            for i, n in enumerate(h.names):
                self.emit(f"{local(n)} := {f}.Args[{i}]")
                self.emit(f"_ = {local(n)}")
            self.assign(r, h.body)
            self.ind -= 1
        self.emit("}")
        self.ind -= 1
        self.emit("}")
        return r
