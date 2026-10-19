"""Symbol query commands over the checked program index."""
from __future__ import annotations

import sys
from pathlib import Path

from .cli_common import USAGE, _flags, _open


def _sym_cmd(name, args, spec, need_paths=False):
    try:
        flags, pos = _flags(args, spec)
    except ValueError as ex:
        sys.stderr.write(f"lm {name}: {ex}\n" + USAGE)
        return None
    if not pos:
        sys.stderr.write(f"lm {name}: missing SYM (module.name)\n" + USAGE)
        return None
    return flags, pos



def _int_flag(flags, key, default):
    return int(flags[key]) if key in flags else default



def cmd_index(args) -> int:
    from .loader import STDLIB

    try:
        flags, pos = _flags(args, {"--stdlib": False, "--exported": False})
    except ValueError as ex:
        sys.stderr.write(f"lm index: {ex}\n" + USAGE)
        return 3
    paths = pos or [d for d in ("src", "examples") if Path(d).is_dir()]
    extra = sorted(f.stem for f in STDLIB.glob("*.lm")) if "--stdlib" in flags else []
    prog, idx = _open(paths, extra)
    mods = [prog.modules[n] for n in prog.targets]
    for line in idx.index_lines(mods, "--exported" in flags):
        print(line)
    return 0



def cmd_slice(args) -> int:
    from .index import tokens
    from .printer import print_module

    r = _sym_cmd("slice", args, {"--bodies": False, "--depth": True, "--budget": True})
    if r is None:
        return 3
    flags, pos = r
    try:
        depth, budget = _int_flag(flags, "--depth", 1), (_int_flag(flags, "--budget", 0) or None)
    except ValueError:
        sys.stderr.write("lm slice: --depth/--budget need integers\n")
        return 3
    prog, idx = _open([], [pos[0].split(".", 1)[0]])
    sym, err = idx.find(pos[0])
    if sym is None:
        sys.stderr.write(f"lm slice: {err}\n")
        return 3
    bodies = "--bodies" in flags
    if depth > 1 and not bodies:
        sys.stderr.write("note: --depth > 1 only matters with --bodies; using depth 1\n")
    text, items, dropped = idx.slice(sym.qual, bodies, depth, budget)
    sys.stdout.write(text)
    whole = sum(tokens(print_module(m.root)) for m in prog.modules.values())
    msg = f"slice {sym.qual}: {len(items)} symbols, {tokens(text)} tokens (loaded modules: {whole})"
    if dropped:
        msg += f"; dropped for budget: {' '.join(dropped)}"
    sys.stderr.write(msg + "\n")
    return 0



def cmd_callers(args) -> int:
    r = _sym_cmd("callers", args, {})
    if r is None:
        return 3
    _, pos = r
    paths = pos[1:] or [d for d in ("src", "examples") if Path(d).is_dir()]
    prog, idx = _open(paths, [pos[0].split(".", 1)[0]])
    sym, err = idx.find(pos[0])
    if sym is None:
        sys.stderr.write(f"lm callers: {err}\n")
        return 3
    by: dict = {}
    for o, p in idx.callers(sym.qual):
        if prog.modules[o.split(".", 1)[0]].is_target or True:
            by.setdefault(o, []).append(p)
    for o in sorted(by):
        print(f"{o}  {' '.join(by[o])}")
    sys.stderr.write(f"callers {sym.qual}: {len(by)} symbol(s)\n")
    return 0



def cmd_deps(args) -> int:
    r = _sym_cmd("deps", args, {"--depth": True})
    if r is None:
        return 3
    flags, pos = r
    prog, idx = _open([], [pos[0].split(".", 1)[0]])
    sym, err = idx.find(pos[0])
    if sym is None:
        sys.stderr.write(f"lm deps: {err}\n")
        return 3
    for q, d in idx.deps(sym.qual, _int_flag(flags, "--depth", 1)):
        print(f"{d} {idx.kind(q)} {q}")
    return 0



def cmd_hash(args) -> int:
    r = _sym_cmd("hash", args, {})
    if r is None:
        return 3
    _, pos = r
    prog, idx = _open([], [pos[0].split(".", 1)[0]])
    sym, err = idx.find(pos[0])
    if sym is None:
        sys.stderr.write(f"lm hash: {err}\n")
        return 3
    print(f"{sym.qual} {idx.hash(sym.qual)}")
    return 0



def cmd_explain(args) -> int:
    from .explain import explain

    r = _sym_cmd("explain", args, {})
    if r is None:
        return 3
    _, pos = r
    paths = pos[1:] or [d for d in ("src", "examples") if Path(d).is_dir()]
    prog, idx = _open(paths, [pos[0].split(".", 1)[0]])
    sym, err = idx.find(pos[0])
    if sym is None or sym.kind != "fn":
        sys.stderr.write(f"lm explain: {err or pos[0] + ' is not a function'}\n")
        return 3
    sys.stdout.write(explain(prog, idx, sym.info))
    return 0

