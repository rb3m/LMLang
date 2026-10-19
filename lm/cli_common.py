"""Shared CLI flag parsing, program loading, and diagnostic reporting."""
from __future__ import annotations

import sys

from .commands import USAGE



def _static(paths, extra=()):
    from .check import Checker
    from .loader import load

    prog = load(paths, extra)
    ck = Checker(prog)
    ck.run()
    return prog, ck



def _report(prog_diags, summary):
    diags = sorted(prog_diags, key=lambda d: (d.file, d.line, d.col, d.code, d.path))
    for d in diags:
        print(d.to_json())
    e = sum(d.severity == "error" for d in diags)
    sys.stderr.write(summary(e, len(diags) - e))
    return e



def _flags(args, spec):
    """spec: {'--name': takes_value}. Returns (flags, positionals) or raises ValueError."""
    flags, pos, i = {}, [], 0
    while i < len(args):
        a = args[i]
        if a.startswith("--"):
            if a not in spec:
                raise ValueError(f"unknown flag {a}")
            if spec[a]:
                if i + 1 >= len(args):
                    raise ValueError(f"{a} needs a value")
                flags[a] = args[i + 1]
                i += 1
            else:
                flags[a] = True
        else:
            pos.append(a)
        i += 1
    return flags, pos



def _open(paths, extra=(), defaults=True):
    from .check import Checker
    from .index import Index
    from .loader import load

    prog = load(paths, extra, defaults)
    ck = Checker(prog)
    ck.check_all = True
    ck.run()
    errs = sum(d.severity == "error" for d in prog.diags)
    if errs:
        sys.stderr.write(f"note: {errs} error(s) in loaded modules; answers may be incomplete (run `check`)\n")
    return prog, Index(prog)

