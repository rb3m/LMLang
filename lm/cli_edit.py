"""Parse edit operations, apply changes, and report their checks."""
from __future__ import annotations

import sys
from pathlib import Path

from .cli_common import USAGE, _open
from .cli_project import cmd_fmt


def cmd_edit(args) -> int:
    import difflib
    import json
    from collections import Counter

    from .check import Checker
    from .edit import OPS, EditError, Work, apply_json, remove_decl, rename
    from .loader import load
    from .printer import format_text, print_module

    ins, pos, dry, force, i = [], [], False, False, 0
    while i < len(args):
        a = args[i]
        if a == "--in" and i + 1 < len(args):
            ins.append(args[i + 1])
            i += 1
        elif a == "--dry-run":
            dry = True
        elif a == "--force":
            force = True
        elif a.startswith("--"):
            sys.stderr.write(f"lm edit: unknown flag {a}\n" + USAGE)
            return 3
        else:
            pos.append(a)
        i += 1
    if not pos or (pos[0] not in OPS and pos[0] != "apply"):
        sys.stderr.write("lm edit: operations:\n" + "".join(f"  {k} {v[2]}\n" for k, v in sorted(OPS.items())) + "  apply JSON   (a diagnostic's `fix` object or list)\n")
        return 3
    op, oargs = pos[0], pos[1:]
    if op == "apply":
        if len(oargs) != 1:
            sys.stderr.write("lm edit apply: expects one JSON argument ('-' reads stdin)\n")
            return 3
        if oargs[0] == "-":
            oargs = [sys.stdin.read()]
        try:
            fx = json.loads(oargs[0])
        except ValueError as ex:
            sys.stderr.write(f"lm edit apply: bad JSON: {ex}\n")
            return 3
        fx = fx if isinstance(fx, list) else [fx]
        names = set()
        for f in fx:
            for k in ("module", "fn"):
                if k in f:
                    names.add(f[k].split(".", 1)[0])
            if "path" in f:
                names.add(f["path"].split("/")[0])
        if any(f.get("op") == "fmt" for f in fx):
            if len(fx) != 1:
                sys.stderr.write("lm edit apply: `fmt` fixes cannot be mixed with others\n")
                return 3
            return cmd_fmt([fx[0]["file"]])
    else:
        want = OPS[op][1]
        if len(oargs) != want:
            sys.stderr.write(f"lm edit {op}: expects {want} argument(s): {OPS[op][2]}\n")
            return 3
        a0 = oargs[0]
        if op == "rename":
            from .edit_variant import check_spelling
            err_msg = check_spelling(a0)
            if err_msg:
                sys.stderr.write(f"lm edit rename: {err_msg}\n")
                return 3
        names = {a0.split("/")[0] if op == "replace-ref" else a0.split(".", 1)[0]}
    paths = ins or [d for d in ("src", "examples") if Path(d).is_dir()]
    for p in paths:
        if not Path(p).exists():
            sys.stderr.write(f"lm edit: no such path: {p}\n")
            return 3
    prog, idx = _open(paths, sorted(names), not ins)
    before = Counter((d.file, d.code) for d in prog.diags if d.severity == "error")
    w = Work(prog, idx)
    try:
        if op == "apply":
            apply_json(w, oargs[0])
        elif op in ("remove-fn", "remove-decl"):
            remove_decl(w, oargs, force)
        elif op == "rename":
            rename(w, oargs, force)
        else:
            OPS[op][0](w, oargs)
    except EditError as ex:
        for d in ex.diags:
            print(d.to_json())
        sys.stderr.write(f"edit {op}: refused: {ex}\n")
        return 1
    olds = {n: (prog.modules[n].file, prog.modules[n].text) for n in w.changed}
    news = {n: print_module(w.roots[n]) for n in w.changed}
    if dry:
        for n in sorted(news):
            sys.stdout.write("".join(l + "\n" for l in difflib.unified_diff(olds[n][1].splitlines(), news[n].splitlines(), olds[n][0], olds[n][0] + " (edited)", lineterm="", n=1)))
        for p in sorted(w.scenario_news):
            sys.stdout.write("".join(l + "\n" for l in difflib.unified_diff(w.scenario_olds[p].splitlines(), w.scenario_news[p].splitlines(), str(p), str(p) + " (edited)", lineterm="", n=1)))
        return 0
    for n in sorted(news):
        Path(olds[n][0]).write_text(news[n], encoding="utf-8")
    for p in sorted(w.scenario_news):
        Path(p).write_text(w.scenario_news[p], encoding="utf-8")
    prog2 = load(paths, sorted(names), not ins)
    Checker(prog2).run()
    after = Counter((d.file, d.code) for d in prog2.diags if d.severity == "error")
    if op == "rename" and after - before:
        for n in sorted(news):
            Path(olds[n][0]).write_text(olds[n][1], encoding="utf-8")
        for p in sorted(w.scenario_olds):
            Path(p).write_text(w.scenario_olds[p], encoding="utf-8")
        for d in sorted(prog2.diags, key=lambda d: (d.file, d.line, d.code)):
            if d.severity == "error":
                print(d.to_json())
        sys.stderr.write("edit rename: aborted, it would introduce errors; nothing written\n")
        return 1
    diags = sorted(prog2.diags, key=lambda d: (d.file, d.line, d.col, d.code, d.path))
    for d in diags:
        print(d.to_json())
    e = sum(d.severity == "error" for d in diags)
    sys.stderr.write(f"edit {op}: wrote {', '.join(Path(olds[n][0]).name for n in sorted(news))}; check: {e} errors, {len(diags) - e} warnings\n")
    if w.scenario_news:
        files = ", ".join(str(p) for p in sorted(w.scenario_news))
        sys.stderr.write(f"edit {op}: rewrote scenarios in {files}; touched scenarios are now proposed and need the owner's re-approval (ADR-055)\n")
    return 1 if e else 0

