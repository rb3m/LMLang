"""Go backend: a printer over the IR (`ir.py`) producing one `package main` file (ADR-026, ADR-035).

The runtime it relies on lives in lm/runtime/go/*.go and is copied next to the generated file.
Every LM value is a Go `Value` (= any); see value.go. Expressions are linearized into statements:
`expr()` returns a Go expression of type Value and may first append statements to the current
block. Left-to-right evaluation is kept by spilling an argument into a temporary whenever a later
argument emitted statements.
"""
from __future__ import annotations

import re
from pathlib import Path

from . import ir
from .gobackend_expr import GoExprMixin
from .gobackend_names import golit, local, mangle, prim_name

RUNTIME = Path(__file__).resolve().parent / "runtime" / "go"
IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


class GoGen(GoExprMixin):
    def __init__(self, prog: ir.Program, contracts: bool = True):
        self.prog, self.contracts = prog, contracts
        self.sites: dict = {}  # Site -> index
        self.lines: list = []
        self.lifted: list = []  # lifted lambda functions
        self.ind = 0
        self.n = 0
        self.lam_n = 0
        self.owner = ""  # fn id whose code is being emitted (names lifted lambdas)

    # ---- low-level helpers --------------------------------------------------------------------
    def site(self, s: ir.Site) -> int:
        return self.sites.setdefault(s, len(self.sites))

    def emit(self, s: str):
        self.lines.append("\t" * self.ind + s)

    def tmp(self) -> str:
        self.n += 1
        return f"t{self.n}"

    def block(self, opener: str, fn, closer: str = "}"):
        self.emit(opener)
        self.ind += 1
        fn()
        self.ind -= 1
        self.emit(closer)

    def assign(self, target: str, e):
        """Emit statements so that `target` (already declared) holds the value of e."""
        self.emit(f"{target} = {self.expr(e)}")

    def args(self, es) -> list:
        """Go expressions for es, evaluated left to right (spill when later args emit statements)."""
        outs = []
        for e in es:
            s = self.expr(e)
            outs.append((s, len(self.lines)))
        res = [s for s, _ in outs]
        for i in range(len(outs) - 1, -1, -1):
            s, at = outs[i]
            if at != len(self.lines) and not IDENT.fullmatch(s):
                t = self.tmp()
                self.lines.insert(at, "\t" * self.ind + f"{t} := Value({s})")
                res[i] = t
        return res

    def spill(self, s: str) -> str:
        if IDENT.fullmatch(s):
            return s
        t = self.tmp()
        self.emit(f"{t} := Value({s})")
        return t

    # ---- expressions -----------------------------------------------------------------------------
    def expr(self, e) -> str:
        return getattr(self, "x_" + type(e).__name__)(e)

    # ---- functions and files -----------------------------------------------------------------------
    def contract(self, c: ir.Contract, params):
        def body():
            ok = self.expr(c.expr)
            args = "".join(", " + local(p) for p in params)
            self.emit(f"if !{ok}.(bool) {{")
            self.emit(f"\tviolation({golit(c.code)}, {self.site(c.site)}{args})")
            self.emit("}")
        self.block("{", body)

    def fn(self, f: ir.Fn):
        self.n, self.owner = 0, f.fid
        ps = ", ".join(local(p) + " Value" for p in f.params)

        def body():
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
            self.emit(f"res := Value({res})")
            if self.contracts and f.ensures:
                self.emit("v_result := res")
                self.emit("_ = v_result")
                for c in f.ensures:
                    self.contract(c, f.params)
            self.emit("depth--")
            self.emit("return res")
        self.block(f"func {mangle(f.fid, 'F_')}({ps}) Value {{", body)
        self.emit("")

    def tail_fn(self, f):
        """One host frame, fresh lexical parameter bindings on every iteration."""
        keep = self.contracts and bool(f.ensures)
        for k, p in enumerate(f.params):
            self.emit(f"next{k} := {local(p)}")
        if keep:
            self.emit("var saved [][]Value")
        self.emit("var res Value")

        def iteration():
            for k, p in enumerate(f.params):
                self.emit(f"{local(p)} := next{k}")
                self.emit(f"_ = {local(p)}")
            for c in f.requires if self.contracts else []:
                self.contract(c, f.params)
            if keep:
                self.emit("saved = append(saved, []Value{" + ", ".join(local(p) for p in f.params) + "})")
            self.assign("res", f.body)
            self.emit("break")
        self.block("for {", iteration)
        if keep:
            def postconditions():
                for k, p in enumerate(f.params):
                    self.emit(f"{local(p)} := saved[i][{k}]")
                    self.emit(f"_ = {local(p)}")
                self.emit("v_result := res")
                self.emit("_ = v_result")
                for c in f.ensures:
                    self.contract(c, f.params)
            self.block("for i := len(saved)-1; i >= 0; i-- {", postconditions)
        self.emit("depth--")
        self.emit("return res")

    def consts(self) -> list:
        lines = []
        self.n = 0
        for cid in self.prog.const_order:
            c = self.prog.consts[cid]
            self.lines = []
            self.ind = 1
            self.owner = cid
            self.assign(mangle(cid, "K_"), c.expr)
            lines += self.lines
        return lines

    def header(self, const_lines: list | None = None) -> list:
        out = ["// Code generated by `lm build` from LM sources; DO NOT EDIT.", "package main", ""]
        decls = []
        for c in sorted(self.prog.ctors):
            ctor = (f"jsonCtors[{golit(c)}]" if c.startswith("json.") else
                    "procExitedCtor" if c == "proc.Exited" else
                    "procSignaledCtor" if c == "proc.Signaled" else
                    f"&Ctor{{{golit(c)}}}")
            decls.append(f"\t{mangle(c, 'C_')} = {ctor}")
            decls.append(f"\t{mangle(c, 'N_')} Value = &Variant{{{mangle(c, 'C_')}, nil}}")
        for r in sorted(self.prog.records):
            fields = ", ".join(golit(x) for x in self.prog.records[r])
            value = ("httpResponseType" if r == "http.Response" else
                     "httpRequestType" if r == "http.Request" else
                     "procResultType" if r == "proc.Result" else
                     "patMatchType" if r == "pat.Match" else
                     f"&RecType{{{golit(r)}, []string{{{fields}}}}}")
            decls.append(f"\t{mangle(r, 'R_')} = {value}")
        for cid in self.prog.const_order:
            decls.append(f"\t{mangle(cid, 'K_')} Value")
        if decls:
            out += ["var (", *decls, ")", ""]
        rows = [f"\t\t{{{golit(s.file)}, {s.line}, {s.col}, {golit(s.path)}, {golit(s.fn)}}}," for s in self.sites]
        std = ", ".join(f"{golit(m)}: true" for m in sorted(self.prog.stdlib))
        init_body = ["func init() {", "\tsites = []Site{", *rows, "\t}", f"\tstdlibMods = map[string]bool{{{std}}}"]
        if const_lines:
            init_body += const_lines
        init_body += ["}", ""]
        out += init_body
        return out

    def program(self, main_lines: list) -> str:
        body: list = []
        for fid in sorted(self.prog.fns):
            self.lines = []
            self.fn(self.prog.fns[fid])
            body += self.lines
        const_lines = self.consts()
        return "\n".join(self.header(const_lines) + body + self.lifted + main_lines) + "\n"


def emit_main(prog: ir.Program, entry: str, entry_site: ir.Site,
              contracts: bool = True, serve=False) -> str:
    g = GoGen(prog, contracts)
    s = g.site(entry_site)
    call = (f"runServe(func(req Value) Value {{ return {mangle(entry, 'F_')}(req) }}, {s})"
            if serve else f"runMain(func() Value {{ return {mangle(entry, 'F_')}() }}, {s})")
    main = ["func main() {", f"\t{call}", "}"]
    return g.program(main)


def emit_cases(prog: ir.Program, cases, contracts: bool = True) -> str:
    """A harness binary printing one outcome line per (label, fid, args) case (see rt.go runCases)."""
    g = GoGen(prog, contracts)
    g.lines, g.ind = [], 2
    for label, fid, args in cases:
        g.n, g.owner = 0, fid
        g.emit(f"{{{golit(label)}, func() Value {{")
        g.ind += 1
        g.emit(f"return {mangle(fid, 'F_')}({', '.join(g.args(args))})")
        g.ind -= 1
        g.emit("}},")
    rows, g.ind = g.lines, 0
    return g.program(["func main() {", "\trunCases([]Case{", *rows, "\t})", "}"])
