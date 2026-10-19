"""Formatting, checking, example testing, and benchmarks."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from .cli_common import USAGE, _report, _static
from .diag import has_errors, make
from .printer import format_text


def _collect(paths):
    files = []
    for p in paths:
        pp = Path(p)
        if pp.is_dir():
            files += sorted(f for f in pp.rglob("*.lm") if not any(part.startswith(".") for part in f.parts))
        elif pp.is_file():
            files.append(pp)
        else:
            return None, p
    return files, None



def cmd_fmt(args) -> int:
    check = "--check" in args
    to_stdout = "--stdout" in args
    paths = [a for a in args if not a.startswith("--")]
    unknown = [a for a in args if a.startswith("--") and a not in ("--check", "--stdout")]
    if unknown:
        sys.stderr.write(f"lm fmt: unknown flag {unknown[0]}\n" + USAGE)
        return 3
    if not paths:
        paths = [d for d in ("src", "stdlib", "examples") if Path(d).is_dir()]
    files, missing = _collect(paths)
    if files is None:
        sys.stderr.write(f"lm fmt: no such path: {missing}\n")
        return 3
    rc, changed = 0, 0
    for f in files:
        text = f.read_text(encoding="utf-8")
        out, diags = format_text(text, str(f))
        for d in diags:
            print(d.to_json())
        if out is None or has_errors(diags):
            rc = 1
            continue
        if to_stdout:
            sys.stdout.write(out)
        elif out != text:
            if check:
                name = out.split(None, 2)[1] if out.startswith("(module") else ""
                print(make("E-NONCANONICAL", str(f), 1, 1, "file is not in canonical form; run `lm fmt`",
                           path=name, fix=[{"op": "fmt", "file": str(f)}]).to_json())
                rc = 1
            else:
                f.write_text(out, encoding="utf-8")
                changed += 1
    if not to_stdout:
        sys.stderr.write(f"fmt: {len(files)} files, {changed} rewritten\n")
    return rc



def cmd_check(args) -> int:
    from .check import Checker
    from .loader import load

    if [a for a in args if a.startswith("--")]:
        sys.stderr.write("lm check: no flags in this version\n" + USAGE)
        return 3
    paths = args or [d for d in ("src", "examples") if Path(d).is_dir()]
    for p in paths:
        if not Path(p).exists():
            sys.stderr.write(f"lm check: no such path: {p}\n")
            return 3
    prog = load(paths)
    scenarios = not args and Path('tests/accept').is_dir()
    if scenarios:
        from .accept import load_scenarios

        scs, _ = load_scenarios('tests/accept')
        extra = sorted({s.module for s in scs
                        if s.module in prog.available
                        and s.module not in prog.modules})
        if extra:
            prog = load(paths, extra=extra)
    ck = Checker(prog)
    ck.run()
    if scenarios:
        from .accept_validate import scenario_diags

        prog.diags.extend(scenario_diags(prog, ck))
    diags = sorted(prog.diags, key=lambda d: (d.file, d.line, d.col, d.code, d.path))
    for d in diags:
        print(d.to_json())
    e = sum(d.severity == "error" for d in diags)
    sys.stderr.write(f"check: {len(prog.targets)} modules, {e} errors, {len(diags) - e} warnings\n")
    return 1 if e else 0



def cmd_test(args) -> int:
    from .runner import test_program

    if [a for a in args if a.startswith("--")]:
        sys.stderr.write("lm test: no flags in this version\n" + USAGE)
        return 3
    paths = args or [d for d in ("src", "examples") if Path(d).is_dir()]
    for p in paths:
        if not Path(p).exists():
            sys.stderr.write(f"lm test: no such path: {p}\n")
            return 3
    prog, _ = _static(paths)
    if _report(prog.diags, lambda e, w: f"check: {len(prog.targets)} modules, {e} errors, {w} warnings\n"):
        sys.stderr.write("test: not run (fix check errors first)\n")
        return 1
    diags, st = test_program(prog)
    cases = f", {st['cases']} runtime cases" if st["cases"] else ""
    e = _report(diags, lambda e, w: f"test: {st['examples']} examples{cases}, {st['failed']} failed; {len(st['no_examples'])} pure fn(s) without examples\n")
    return 1 if e else 0



def _load_count_tokens():
    """bench/count_tokens.py is a dev-only tool outside the package (ADR-051 item 5)."""
    import importlib.util

    path = Path(__file__).resolve().parents[1] / "bench" / "count_tokens.py"
    spec = importlib.util.spec_from_file_location("lm_bench_count_tokens", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def cmd_bench(args) -> int:
    from .bench import ROOT, run_all, task_dirs

    if "--project" in args:
        from .bench_project import cmd_bench_project
        return cmd_bench_project(args)

    if args and args != ["--tokenizer", "anthropic"]:
        sys.stderr.write("usage: lm bench [--tokenizer anthropic] | lm bench --project PATH [--json]\n")
        return 3
    ct = _load_count_tokens() if args else None
    try:
        counter = ct.Counter() if ct else None
    except ct.TokenizerUnavailable as e:
        sys.stderr.write(f"error: {e}\n")
        return 1
    run_all()
    out = ROOT / "bench" / "results"
    if counter:
        try:
            res = ct.s5_real(task_dirs(), counter)
        except ct.TokenizerUnavailable as e:
            sys.stderr.write(f"error: {e}\n")
            return 1
        (out / "s5-anthropic.json").write_text(json.dumps(res, indent=1, sort_keys=True) + "\n")
        with (out / "summary.md").open("a") as f:
            f.write(ct.summary_section(res))
    sys.stdout.write((out / "summary.md").read_text())
    return 0

