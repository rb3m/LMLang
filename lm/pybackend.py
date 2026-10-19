"""Python backend: a printer over the IR (`ir.py`) producing one self-contained Python file (ADR-062)."""
from __future__ import annotations

import re
from pathlib import Path

from . import ir
from .pybackend_embed import generate_embedded_runtime
from .pybackend_expr import PyExprMixin
from .pybackend_names import local, mangle, pylit, prim_name

RUNTIME = Path(__file__).resolve().parent / "runtime" / "py"
IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


class BuildError(Exception):
    def __init__(self, msg: str, code: int = 1):
        super().__init__(msg)
        self.code = code


def check_features(prog: ir.Program):
    pass


class PyGen(PyExprMixin):
    def __init__(self, prog: ir.Program, contracts: bool = True):
        self.prog, self.contracts = prog, contracts
        self.sites: dict = {}  # Site -> index
        self.lines: list = []
        self.lifted: list = []  # lifted lambda functions
        self.ind = 0
        self.n = 0
        self.lam_n = 0
        self.owner = ""

    def site(self, s: ir.Site) -> int:
        return self.sites.setdefault(s, len(self.sites))

    def emit(self, s: str):
        self.lines.append("\t" * self.ind + s)

    def tmp(self) -> str:
        self.n += 1
        return f"t{self.n}"

    def block(self, opener: str, fn):
        self.emit(opener)
        self.ind += 1
        fn()
        self.ind -= 1

    def assign(self, target: str, e):
        if isinstance(e, ir.TailCall):
            self.expr(e)
            return
        self.emit(f"{target} = {self.expr(e)}")

    def args(self, es) -> list:
        outs = []
        for e in es:
            s = self.expr(e)
            outs.append((s, len(self.lines)))
        res = [s for s, _ in outs]
        for i in range(len(outs) - 1, -1, -1):
            s, at = outs[i]
            if at != len(self.lines) and not IDENT.fullmatch(s):
                t = self.tmp()
                self.lines.insert(at, "\t" * self.ind + f"{t} = {s}")
                res[i] = t
        return res

    def spill(self, s: str) -> str:
        if IDENT.fullmatch(s):
            return s
        t = self.tmp()
        self.emit(f"{t} = {s}")
        return t

    def expr(self, e) -> str:
        return getattr(self, "x_" + type(e).__name__)(e)

    def contract(self, c: ir.Contract, params):
        ok = self.expr(c.expr)
        args = "".join(", " + local(p) for p in params)
        self.emit(f"if not {ok}:")
        self.emit(f"\tviolation({pylit(c.code)}, {self.site(c.site)}{args})")

    def fn(self, f: ir.Fn):
        self.n, self.owner = 0, f.fid
        ps = ", ".join(local(p) for p in f.params)

        def body():
            self.emit("global depth")
            self.emit("enter()")
            if f.tail:
                self.tail_fn(f)
                return
            for c in f.requires if self.contracts else []:
                self.contract(c, f.params)
            if f.prim is not None:
                res = f"{prim_name(f.prim)}({', '.join(local(p) for p in f.params)})"
            else:
                res = self.expr(f.body)
            self.emit(f"res = {res}")
            if self.contracts and f.ensures:
                self.emit("v_result = res")
                for c in f.ensures:
                    self.contract(c, f.params)
            self.emit("depth -= 1")
            self.emit("return res")

        self.block(f"def {mangle(f.fid, 'F_')}({ps}):", body)
        self.emit("")

    def tail_fn(self, f: ir.Fn):
        keep = self.contracts and bool(f.ensures)
        for k, p in enumerate(f.params):
            self.emit(f"next{k} = {local(p)}")
        if keep:
            self.emit("saved = []")
        self.emit("res = UNIT")

        def iteration():
            for k, p in enumerate(f.params):
                self.emit(f"{local(p)} = next{k}")
            for c in f.requires if self.contracts else []:
                self.contract(c, f.params)
            if keep:
                params_tuple = "(" + ", ".join(local(p) for p in f.params) + ("," if len(f.params) == 1 else "") + ")"
                self.emit(f"saved.append({params_tuple})")
            self.assign("res", f.body)
            self.emit("break")

        self.block("while True:", iteration)
        if keep:
            def postconditions():
                for k, p in enumerate(f.params):
                    self.emit(f"{local(p)} = saved_item[{k}]")
                self.emit("v_result = res")
                for c in f.ensures:
                    self.contract(c, f.params)
            self.block("for saved_item in reversed(saved):", postconditions)
        self.emit("depth -= 1")
        self.emit("return res")

    def consts(self) -> list:
        lines = []
        self.n = 0
        for cid in self.prog.const_order:
            c = self.prog.consts[cid]
            self.lines = []
            self.ind = 0
            self.owner = cid
            self.assign(mangle(cid, "K_"), c.expr)
            lines += self.lines
        return lines

    def header(self) -> list:
        embedded_rt = generate_embedded_runtime(self.prog)
        rt_code = (RUNTIME / "rt.py").read_text(encoding="utf-8")
        entry_code = (RUNTIME / "entry.py").read_text(encoding="utf-8")
        out = ["#!/usr/bin/env python3", "# Code generated by `lm build --target py` from LM sources; DO NOT EDIT.",
               "", rt_code, "", embedded_rt, "", entry_code, ""]
        site_rows = [f"\tSite({pylit(s.file)}, {s.line}, {s.col}, {pylit(s.path)}, {pylit(s.fn)})," for s in self.sites]
        out += ["sites.extend([", *site_rows, "])", ""]
        std = ", ".join(pylit(m) for m in sorted(self.prog.stdlib))
        out += [f"stdlib_mods.update([{std}])", ""]
        return out

    def program(self, main_lines: list) -> str:
        body: list = []
        for fid in sorted(self.prog.fns):
            self.lines = []
            self.fn(self.prog.fns[fid])
            body += self.lines
        const_lines = self.consts()
        return "\n".join(self.header() + body + self.lifted + const_lines + main_lines) + "\n"


def emit_main(prog: ir.Program, entry: str, entry_site: ir.Site, contracts: bool = True) -> str:
    check_features(prog)
    g = PyGen(prog, contracts)
    s = g.site(entry_site)
    main = ["if __name__ == '__main__':", f"\trun_main(lambda: {mangle(entry, 'F_')}(), {s})"]
    return g.program(main)


def emit_cases(prog: ir.Program, cases, contracts: bool = True) -> str:
    check_features(prog)
    g = PyGen(prog, contracts)
    case_fns = []
    case_tuples = []
    for k, (label, fid, args) in enumerate(cases):
        g.n, g.owner = 0, fid
        saved = (g.lines, g.ind)
        g.lines, g.ind = [], 0
        fn_name = f"case_{k}"

        def body():
            g.emit("global depth")
            a = g.args(args)
            g.emit(f"return {mangle(fid, 'F_')}({', '.join(a)})")

        g.block(f"def {fn_name}():", body)
        g.emit("")
        case_fns += g.lines
        g.lines, g.ind = saved
        case_tuples.append(f"\t\t({pylit(label)}, {fn_name}),")
    main = [*case_fns, "if __name__ == '__main__':", "\trun_cases([", *case_tuples, "\t])"]
    return g.program(main)
