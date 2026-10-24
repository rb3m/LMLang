"""Discover, read, canonicalize and link modules into a Program."""
from __future__ import annotations

from pathlib import Path

from .ast import canonicalize
from .diag import ExternalFile, has_errors, make
from .deps import MANIFEST, cache_path, read_cached, read_pins
from .printer import print_module
from .program import ModInfo, Program
from .sexpr import Atom, read

PKG_ROOT = Path(__file__).resolve().parent.parent
STDLIB = PKG_ROOT / "stdlib"


def _scan(d: Path, recursive: bool):
    if not d.is_dir():
        return []
    it = d.rglob("*.lm") if recursive else d.glob("*.lm")
    return sorted(f for f in it if not any(p.startswith(".") for p in f.relative_to(d).parts))


def load(paths, extra=(), defaults=True) -> Program:
    prog = Program()
    targets: list = []
    search = []  # (dir, recursive)
    for p in paths:
        pp = Path(p)
        if pp.is_dir():
            targets += _scan(pp, True)
            search.append((pp, True))
        else:
            targets.append(pp)
            search.append((pp.parent, False))
    search += ([(Path("src"), True), (Path("examples"), True)] if defaults else []) + [(STDLIB, True)]
    seen_files: dict = {}  # stem -> resolved path
    for d, rec in search:
        for f in _scan(d, rec):
            r = f.resolve()
            if f.stem in seen_files:
                if seen_files[f.stem] != r:
                    prog.diags.append(make("E-DUP-NAME", str(f), 1, 1, f"module `{f.stem}` is also defined in {seen_files[f.stem]}"))
                continue
            seen_files[f.stem] = r
            prog.available[f.stem] = f
    for t in targets:  # explicit targets are always available under their stem
        prog.available.setdefault(t.stem, t)
    pins, diags = read_pins()
    prog.diags.extend(diags)
    prog.pins = {p.stem: p for p in pins}
    external = {}
    for pin in pins:
        if pin.stem in prog.available:
            prog.diags.append(make('E-DUP-NAME', MANIFEST, pin.line, pin.col,
                                   f'pinned module `{pin.stem}` also exists in a search path or stdlib'))
            continue
        data, problem = read_cached(pin)
        if problem:
            prog.diags.append(make(problem, MANIFEST, pin.line, pin.col,
                                   f'cached bytes for `{pin.stem}` are missing or do not match the pin',
                                   fix=[{'op': 'fetch'}]))
            continue
        prog.available[pin.stem] = cache_path(pin)
        external[pin.stem] = data
    target_set = {t.resolve() for t in targets}
    for name, data in sorted(external.items()):
        _load_file(prog, prog.available[name], False, data=data)
    for t in sorted(set(targets), key=str):
        _load_file(prog, t, True)
    for name in extra:  # external bytes were already verified and parsed above
        if name in prog.available and name not in external:
            _load_file(prog, prog.available[name], True)
    pending = list(prog.modules)
    while pending:
        m = prog.modules[pending.pop()]
        for u in m.uses:
            name = u.value
            if m.is_external and not (
                    name in prog.available and STDLIB.resolve() in prog.available[name].resolve().parents):
                prog.diags.append(make('E-DEP-UNPINNED', m.file, u.line, u.col,
                                       f'external module may use only stdlib modules; found `{name}`', path=f'{m.name}/use'))
                continue
            if name not in prog.modules and name in prog.available and name not in external:
                f = prog.available[name]
                _load_file(prog, f, f.resolve() in target_set)
                if name in prog.modules:
                    pending.append(name)
    prog.targets = sorted(n for n, m in prog.modules.items() if m.is_target)
    _cycles(prog)
    return prog


def _load_file(prog: Program, f: Path, is_target: bool, data=None):
    name = f.stem
    if name in prog.modules:
        return
    file = ExternalFile(str(f)) if data is not None else str(f)
    try:
        text = data.decode("utf-8") if data is not None else f.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as ex:
        prog.diags.append(make('E-PARSE', file, 1, 1, f'cannot read module: {ex}'))
        return
    root, diags = read(text, file)
    canon = None
    if root is not None:
        canon, d2 = canonicalize(root, file)
        diags += d2
    prog.diags.extend(diags)
    if canon is None or has_errors(diags):
        return
    if canon.items[1].value != name:
        prog.diags.append(make("E-PARSE", file, root.line, root.col, f"module name `{canon.items[1].value}` must match file name `{name}.lm`"))
        return
    if is_target and print_module(canon) != text:
        prog.diags.append(make("E-NONCANONICAL", file, 1, 1, "file is not in canonical form; run `lm fmt`", path=name, fix=[{"op": "fmt", "file": file}]))
    is_std = STDLIB.resolve() in f.resolve().parents
    m = ModInfo(name=name, file=file, is_stdlib=is_std and data is None, is_target=is_target, root=canon,
                is_external=data is not None, text=text)
    for c in canon.items[2:]:
        if c.items[0].value == "use":
            m.uses = list(c.items[1:])
    prog.modules[name] = m


def _cycles(prog: Program):
    state: dict = {}

    def visit(n, stack):
        state[n] = 1
        for u in prog.modules[n].uses:
            t = u.value
            if t not in prog.modules:
                continue
            if state.get(t) == 1:
                cyc = " -> ".join(stack[stack.index(t):] + [t]) if t in stack else f"{n} -> {t}"
                m = prog.modules[n]
                if m.report:
                    prog.diags.append(make("E-CYCLE", m.file, u.line, u.col, f"module cycle: {cyc}", path=f"{n}/use"))
            elif t not in state:
                visit(t, stack + [t])
        state[n] = 2

    for n in sorted(prog.modules):
        if n not in state:
            visit(n, [n])
