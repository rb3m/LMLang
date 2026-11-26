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
    from .deps import extension_files
    from .loader import STDLIB

    try:
        flags, pos = _flags(args, {"--stdlib": False, "--ext": False, "--exported": False,
                                  "--modules": False, "--module": True})
    except ValueError as ex:
        sys.stderr.write(f"lm index: {ex}\n" + USAGE)
        return 3
    catalog = '--modules' in flags
    name = flags.get('--module')
    if (catalog or name is not None) and pos:
        sys.stderr.write('lm index: --modules and --module reject PATH arguments\n')
        return 3
    if catalog and name is not None:
        sys.stderr.write('lm index: --modules and --module '
                         'are mutually exclusive\n')
        return 3
    if catalog and not {'--stdlib', '--ext'} & flags.keys():
        sys.stderr.write('lm index: --modules requires --stdlib or --ext\n')
        return 3
    exported_only = '--exported' in flags
    if name is not None:
        prog, idx = _open([], [name], discover_ext=True)
        mod = prog.modules.get(name)
        if mod is None:
            available = " ".join(sorted(prog.available.keys() | prog.pins.keys()))
            sys.stderr.write(f'lm index: cannot load module {name}; available modules: {available}\n')
            return 3
        for line in idx.index_lines([mod], exported_only, module_detail=True):
            print(line)
        return 0

    paths = pos or [d for d in ("src", "examples") if Path(d).is_dir()]
    stdlib = '--stdlib' in flags
    discover_ext = '--ext' in flags or (catalog and stdlib)
    extra = sorted(f.stem for f in STDLIB.glob("*.lm")) if stdlib else []
    if discover_ext:
        extra.extend(extension_files())
    prog, idx = _open([] if catalog else paths, extra, discover_ext=discover_ext)
    if catalog:
        mods = [prog.modules[n] for n in extra if n in prog.modules]
        for line in idx.module_lines(mods, mark_extensions=stdlib):
            print(line)
        return 0
    mods = [prog.modules[n] for n in sorted(set(prog.targets) |
                                          {n for n, m in prog.modules.items() if m.is_external})]
    for line in idx.index_lines(mods, exported_only):
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
    prog, idx = _open([], [pos[0].split(".", 1)[0]], discover_ext=True)
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
    prog, idx = _open([], [pos[0].split(".", 1)[0]], discover_ext=True)
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
    prog, idx = _open([], [pos[0].split(".", 1)[0]], discover_ext=True)
    sym, err = idx.find(pos[0])
    if sym is None:
        sys.stderr.write(f"lm hash: {err}\n")
        return 3
    print(f"{sym.qual} {idx.hash(sym.qual)}")
    return 0



def cmd_explain(args) -> int:
    from .explain import explain, explain_type

    r = _sym_cmd("explain", args, {})
    if r is None:
        return 3
    _, pos = r
    paths = pos[1:] or [d for d in ("src", "examples") if Path(d).is_dir()]
    prog, idx = _open(paths, [pos[0].split(".", 1)[0]])
    sym, err = idx.find(pos[0])
    if sym is None or sym.kind not in ("fn", "type"):
        sys.stderr.write(f"lm explain: {err or pos[0] + ' is not a function or type'}\n")
        return 3
    text = explain_type(idx, sym.info) if sym.kind == "type" else explain(prog, idx, sym.info)
    sys.stdout.write(text)
    return 0

