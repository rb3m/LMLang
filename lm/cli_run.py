"""Run a checked LM function with explicit effects and arguments."""
from __future__ import annotations

import sys

from .cli_common import USAGE, _report, _static


def cmd_run(args) -> int:
    from .check import Checker
    from .interp import Interp
    from .runner import FAULT_CODES, FAULT_EXIT, in_big_stack, runtime_diag
    from .sexpr import read
    from .rand_prims import parse_seed
    from .values import LmFail, show
    from .accept import check_args

    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", line_buffering=True)
    program_args = []
    if "--" in args:
        boundary = args.index("--")
        args, program_args = args[:boundary], args[boundary + 1:]
    allow, contracts, pos, i = [], True, [], 0
    seed = None
    while i < len(args):
        a = args[i]
        if a == "--allow" and i + 1 < len(args):
            allow.append(args[i + 1])
            i += 2
            continue
        if a == "--seed":
            try:
                if i + 1 >= len(args):
                    raise ValueError("--seed needs a value")
                seed = parse_seed(args[i + 1])
            except ValueError as ex:
                sys.stderr.write(f"lm run: {ex}\n")
                return 3
            i += 2
            continue
        if a == "--no-contracts":
            contracts = False
        elif a.startswith("--"):
            sys.stderr.write(f"lm run: unknown flag {a}\n" + USAGE)
            return 3
        else:
            pos.append(a)
        i += 1
    if not pos or "." not in pos[0]:
        sys.stderr.write(USAGE)
        return 3
    mname, fname = pos[0].split(".", 1)
    prog, ck = _static([], extra=[mname])
    if mname not in prog.modules:
        if not any(d.severity == "error" for d in prog.diags):
            sys.stderr.write(f"lm run: no module `{mname}`\n")
            return 3
    e = _report(prog.diags, lambda e, w: "") if prog.diags else 0
    if e:
        return 1
    f = prog.modules[mname].fns.get(fname)
    if f is None:
        sys.stderr.write(f"lm run: module `{mname}` has no function `{fname}`\n")
        return 3
    nodes = []
    for a in pos[1:]:
        n, d = read(a, "<arg>")
        if n is None:
            _report(d, lambda e, w: "")
            return 1
        nodes.append(n)
    if len(nodes) != len(f.params):
        sys.stderr.write(f"lm run: {f.qual} takes {len(f.params)} argument(s), got {len(nodes)}\n")
        return 3
    m = prog.modules[mname]
    nodes, ft = check_args(ck, m, f, nodes)
    for d in prog.diags:
        if d.path.startswith("arg#"):
            d.file = "<arg>"
    if _report(prog.diags, lambda e, w: ""):
        return 1
    it = Interp(prog, allowed=allow, contracts=contracts, args=program_args, seed=seed)

    def go():
        try:
            return "ok", it.apply(__import__("lm.values", fromlist=["Named"]).Named(f), [it.ev(n, {}, m) for n in nodes])
        except LmFail as x:
            return "fail", x
        except Exception as ex:
            d = runtime_diag(ex, it=it)
            if d is None:
                raise
            return "diag", d

    kind, val = in_big_stack(go)
    if kind == "ok":
        print(show(val))
        return 0
    if kind == "fail":
        print(f"(fail {val.id}" + "".join(" " + show(a) for a in val.args_) + ")", file=sys.stderr)
        return 1
    if val.file == "":
        val.file = m.file
    sys.stdout.flush()
    print(val.to_json(), file=sys.stderr)
    return FAULT_EXIT if val.code in FAULT_CODES else 1

