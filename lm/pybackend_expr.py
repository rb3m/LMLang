"""Python expression emitters mixed into pybackend.PyGen."""
from __future__ import annotations

import struct

from . import ir
from .printer import float_text
from .pybackend_names import local, mangle, pylit

ARITH = {"+": "add", "-": "sub", "*": "mul", "/": "div", "mod": "mod"}
COMPARE = {
    "=": "equal({0}, {1})", "!=": "(not equal({0}, {1}))",
    "<": "less({0}, {1})", "<=": "(not less({1}, {0}))",
    ">": "less({1}, {0})", ">=": "(not less({0}, {1}))",
}


class PyExprMixin:
    def x_Lit(self, e):
        if e.kind == "int":
            return str(e.value)
        if e.kind == "float":
            u = struct.unpack('<Q', struct.pack('<d', e.value))[0]
            return f"fbits(0x{u:016x})"
        if e.kind == "str":
            return pylit(e.value)
        if e.kind == "bool":
            return "True" if e.value else "False"
        return "UNIT"

    def x_Local(self, e):
        return local(e.name)

    def x_ConstRef(self, e):
        return mangle(e.cid, "K_")

    def x_FnRef(self, e):
        return mangle(e.fid, "F_")

    def x_PreludeRef(self, e):
        return f"prelude_values[{pylit(e.op)}]"

    def x_Call(self, e):
        if e.discharged and e.fid in ("list.nth", "vec.nth", "vec.put"):
            a = self.args(e.args)
            fn = e.fid.replace(".", "_")
            return f"safe_{fn}({', '.join(a)}, {self.site(e.site)})"
        return f"{mangle(e.fid, 'F_')}({', '.join(self.args(e.args))})"

    def x_TailCall(self, e):
        temps = []
        for arg in e.args:
            t = self.tmp()
            self.emit(f"{t} = {self.expr(arg)}")
            temps.append(t)
        for k, t in enumerate(temps):
            self.emit(f"next{k} = {t}")
        self.emit("continue")
        return "UNIT"

    def x_PrimOp(self, e):
        a = self.args(e.args)
        if e.op in ARITH:
            fn = ("safe_" + ARITH[e.op]) if (e.discharged and e.op in ("/", "mod")) else ARITH[e.op]
            return f"{fn}({a[0]}, {a[1]}, {self.site(e.site)})"
        if e.op in COMPARE:
            a = [self.spill(x) for x in a]
            return COMPARE[e.op].format(*a)
        if e.op == "not":
            return f"(not {a[0]})"
        if e.op == "len":
            return f"len({a[0]})"
        if e.op == "pair":
            return f"Pair({a[0]}, {a[1]})"
        return f"(({a[0]},) + {a[1]})"

    def x_Apply(self, e):
        f, *a = self.args([e.fn, *e.args])
        return f"{f}({', '.join(a)})"

    def x_If(self, e):
        c = self.expr(e.cond)
        t = self.tmp()
        self.emit(f"if {c}:")
        self.ind += 1
        self.assign(t, e.then)
        self.ind -= 1
        self.emit("else:")
        self.ind += 1
        self.assign(t, e.else_)
        self.ind -= 1
        return t

    def x_Let(self, e):
        v = local(e.name)
        val = self.expr(e.value)
        self.emit(f"{v} = {val}")
        t = self.tmp()
        self.assign(t, e.body)
        return t

    def path(self, subj: str, path: tuple) -> str:
        for step in path:
            if step[0] == "arg":
                subj = f"{subj}.args[{step[1]}]"
            elif step[0] == "elem":
                subj = f"{subj}[{step[1]}]"
            elif step[0] == "tail":
                subj = f"{subj}[1:]"
            elif step[0] == "first":
                subj = f"{subj}.a"
            elif step[0] == "second":
                subj = f"{subj}.b"
        return subj

    def test(self, subj: str, t: ir.Test) -> str:
        p = self.path(subj, t.path)
        if t.kind == "pair":
            return f"isinstance({p}, Pair)"
        if t.kind == "tag":
            return f"has_tag({p}, {pylit(t.value)})"
        if t.kind == "int":
            return f"(type({p}) is int and {p} == {t.value})"
        if t.kind == "str":
            return f"(type({p}) is str and {p} == {pylit(t.value)})"
        if t.kind == "len":
            return f"(isinstance({p}, tuple) and len({p}) == {t.value})"
        if t.kind == "nonempty":
            return f"(isinstance({p}, tuple) and len({p}) > 0)"
        return f"({p} is True)" if t.value else f"({p} is False)"

    def x_Match(self, e):
        s = self.spill(self.expr(e.subject))
        t = self.tmp()
        for k, arm in enumerate(e.arms):
            cond = " and ".join(self.test(s, x) for x in arm.tests) or "True"
            self.emit(("if " if k == 0 else "elif ") + cond + ":")
            self.ind += 1
            for name, p in arm.binds:
                self.emit(f"{local(name)} = {self.path(s, p)}")
            self.assign(t, arm.body)
            self.ind -= 1
        self.emit("else:")
        self.ind += 1
        self.emit('raise RuntimeError("lm: non-exhaustive match (checker bug)")')
        self.ind -= 1
        return t

    def x_Lambda(self, e):
        self.lam_n += 1
        name = f"L{self.lam_n}_{mangle(self.owner, '')}"
        caps, ps = [local(c) for c in e.captures], [local(p) for p in e.params]
        saved = (self.lines, self.ind)
        self.lines, self.ind = [], 0

        def body():
            self.emit(f"return {self.expr(e.body)}")

        self.block(f"def {name}({', '.join(caps + ps)}):", body)
        self.emit("")
        self.lifted += self.lines
        self.lines, self.ind = saved
        caps_str = f"({', '.join(caps) + (',' if len(caps) == 1 else '')})" if caps else "()"
        return f"Closure({name}, {caps_str})"

    def x_Do(self, e):
        if not e.items:
            return "UNIT"
        for x in e.items[:-1]:
            self.emit(f"_ = {self.expr(x)}")
        return self.expr(e.items[-1])

    def x_For(self, e):
        xs = self.spill(self.expr(e.list))
        v = local(e.name)
        elem = self.tmp()

        def body():
            self.emit(f"{v} = {elem}")
            self.emit(f"_ = {self.expr(e.body)}")

        self.block(f"for {elem} in {xs}:", body)
        return "UNIT"

    def x_ListLit(self, e):
        a = self.args(e.items)
        return f"({', '.join(a) + (',' if len(a) == 1 else '')})" if a else "()"

    def x_VecLit(self, e):
        self.vec_literals = True
        return f"Vec.from_iterable([{', '.join(self.args(e.items))}])"

    def x_MapLit(self, e):
        keys = f"({', '.join(self.expr(k) for k in e.keys) + (',' if len(e.keys) == 1 else '')})"
        vals = self.args(e.items)
        vals_str = f"({', '.join(vals) + (',' if len(vals) == 1 else '')})"
        return f"map_of({keys}, {vals_str})"

    def x_SetLit(self, e):
        items = f"({', '.join(self.expr(k) for k in e.items) + (',' if len(e.items) == 1 else '')})"
        return f"set_of({items})"

    def x_Construct(self, e):
        if not e.args:
            if e.ctor == "None":
                return "V_NONE"
            mod, name = (e.ctor.split(".", 1) if "." in e.ctor else ("", e.ctor))
            return f"Var({pylit(mod)}, {pylit(name)}, ())"
        a = self.args(e.args)
        if e.ctor == "Some":
            return f"mk_some({a[0]})"
        mod, name = (e.ctor.split(".", 1) if "." in e.ctor else ("", e.ctor))
        args_str = f"({', '.join(a) + (',' if len(a) == 1 else '')})"
        return f"Var({pylit(mod)}, {pylit(name)}, {args_str})"

    def x_NewRec(self, e):
        vals = {f: self.spill(s) for (f, _), s in zip(e.fields, self.args([x for _, x in e.fields]))}
        order = self.prog.records[e.rtype]
        items_str = ", ".join(f"({pylit(f)}, {vals[f]})" for f in order)
        return f"Rec({pylit(e.rtype)}, ({items_str + (',' if len(order) == 1 else '')}))"

    def x_GetField(self, e):
        return f"get_field({self.expr(e.rec)}, {pylit(e.field)})"

    def x_With(self, e):
        a = self.args([e.rec, *(x for _, x in e.updates)])
        pairs = "".join(f", ({pylit(f)}, {v})" for (f, _), v in zip(e.updates, a[1:]))
        return f"with_fields({a[0]}{pairs})"

    def _andor(self, items: list, cond_fmt: str, empty: str) -> str:
        if not items:
            return empty
        t = self.tmp()
        self.emit(f"{t} = {self.expr(items[0])}")
        opened = 0
        for x in items[1:]:
            self.emit(f"if {cond_fmt.format(t)}:")
            self.ind += 1
            opened += 1
            self.assign(t, x)
        for _ in range(opened):
            self.ind -= 1
        return t

    def x_And(self, e):
        return self._andor(e.items, "{}", "True")

    def x_Or(self, e):
        return self._andor(e.items, "not {}", "False")

    def x_Fail(self, e):
        return f"lm_fail({', '.join([pylit(e.err), *self.args(e.args)])})"

    def x_Try(self, e):
        r, d, fl = self.tmp(), self.tmp(), self.tmp()
        self.emit(f"{d} = depth")
        self.emit("try:")
        self.ind += 1
        self.assign(r, e.body)
        self.ind -= 1
        self.emit(f"except LmFail as {fl}:")
        self.ind += 1
        self.emit(f"depth = {d}")
        for k, h in enumerate(e.handlers):
            self.emit(("if " if k == 0 else "elif ") + f"{fl}.id == {pylit(h.err)}:")
            self.ind += 1
            for i, n in enumerate(h.names):
                self.emit(f"{local(n)} = {fl}.args_[{i}]")
            self.assign(r, h.body)
            self.ind -= 1
        self.emit("else:")
        self.ind += 1
        self.emit(f"raise {fl}")
        self.ind -= 1
        self.ind -= 1
        return r
