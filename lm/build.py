"""`lm build`: checked program -> IR -> Go source -> static native binary (ADR-026, ADR-031, ADR-035).

Also runs examples compiled (`run_examples_go`), used by the differential test against the
interpreter. The `go` toolchain is needed only here; the binaries need nothing.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from . import gobackend, pybackend
from .ir import Site
from .lower import lower, lower_examples
from .types import INT, UNIT

OSES, ARCHES = ("linux", "darwin"), ("amd64", "arm64")
GO_MOD = "module lmprog\n\ngo 1.21\n"
GO_MISSING = ("the Go toolchain (`go`) was not found on PATH or in ~/.local/go, /usr/local/go, /opt/homebrew; install Go >= 1.21 (https://go.dev/dl/) "
              "or set LM_GO=/path/to/go")


class BuildError(Exception):
    """A problem in the user's request or program (reported, exit 1 or 3), not a toolchain bug."""

    def __init__(self, msg, code=1):
        super().__init__(msg)
        self.code = code


# Usual install locations, tried when `go` is not on PATH (official tarball in ~/.local or /usr/local, Homebrew).
GO_FALLBACKS = ("~/.local/go/bin/go", "/usr/local/go/bin/go", "/opt/homebrew/bin/go", "/usr/local/bin/go")


def find_go() -> str | None:
    """The `go` executable: $LM_GO if set, else `go` on PATH, else the first usual install location."""
    env = os.environ.get("LM_GO")
    if env:
        return env if Path(env).is_file() else None
    on_path = shutil.which("go")
    if on_path:
        return on_path
    found = [str(Path(c).expanduser()) for c in GO_FALLBACKS if Path(c).expanduser().is_file()]
    return found[0] if found else None


def entry_problem(f) -> str | None:
    """ADR-031: an entry takes no parameters and returns Unit or Int."""
    if f.params:
        return f"{f.qual} takes {len(f.params)} parameter(s); an entry point takes none (read input with io.args/io.read-line)"
    if f.ret not in (INT, UNIT):
        return f"{f.qual} must return Unit or Int (the exit status)"
    return None


def runtime_prims() -> set:
    """Names of the prim functions the Go runtime implements."""
    names = set()
    for f in gobackend.RUNTIME.glob("*.go"):
        names |= set(re.findall(r"^func (prim_\w+)\(", f.read_text(encoding="utf-8"), re.M))
    return names


def missing_prims(prog: object) -> list:
    have = runtime_prims()
    return sorted(p for p in prog.prims if gobackend.prim_name(p) not in have)


def write_sources(main_go: str, d: Path):
    d.mkdir(parents=True, exist_ok=True)
    for f in sorted(gobackend.RUNTIME.glob("*.go")):
        shutil.copyfile(f, d / f"lm_{f.name}")
    (d / "main.go").write_text(main_go, encoding="utf-8")
    (d / "go.mod").write_text(GO_MOD, encoding="utf-8")


def go_build(go: str, d: Path, out: Path, goos=None, goarch=None):
    env = {**os.environ, "CGO_ENABLED": "0", "GOTOOLCHAIN": "local", "GOFLAGS": "-mod=mod"}
    if goos:
        env["GOOS"] = goos
    if goarch:
        env["GOARCH"] = goarch
    p = subprocess.run([go, "build", "-trimpath", "-buildvcs=false", "-ldflags=-s -w", "-o", str(out.resolve()), "."],
                       cwd=d, env=env, capture_output=True, text=True)
    if p.returncode != 0:  # generated code that does not compile is a toolchain bug
        raise RuntimeError(f"go build failed in {d}:\n{p.stdout}{p.stderr}")


def _check_prims(irp):
    missing = missing_prims(irp)
    if missing:
        names = ", ".join(f"{p} (func {gobackend.prim_name(p)})" for p in missing)
        raise BuildError(f"no Go implementation for prim(s): {names}; add them to lm/runtime/go/prims.go")


def build(prog, f, out: Path, goos=None, goarch=None, contracts=True, keep_go=None, go=None):
    """Compile entry fn `f` (FnInfo) of a checked program to the binary `out`."""
    go = go or find_go()
    if go is None:
        raise BuildError(GO_MISSING, 3)
    problem = entry_problem(f)
    if problem:
        raise BuildError(problem, 3)
    irp = lower(prog, [f.qual])
    _check_prims(irp)
    node = f.node
    site = Site(f.mod.file, node.line, node.col, f"{f.mod.name}/{f.name}", f.qual)
    src = gobackend.emit_main(irp, f.qual, site, contracts)
    if keep_go:
        write_sources(src, Path(keep_go))
        go_build(go, Path(keep_go), out, goos, goarch)
        return
    with tempfile.TemporaryDirectory(prefix="lm-build-") as tmp:
        write_sources(src, Path(tmp))
        go_build(go, Path(tmp), out, goos, goarch)


def build_py(prog, f, out: Path, contracts: bool = True):
    """Compile entry fn `f` (FnInfo) of a checked program to a self-contained Python script."""
    problem = entry_problem(f)
    if problem:
        raise BuildError(problem, 3)
    irp = lower(prog, [f.qual])
    pybackend.check_features(irp)
    node = f.node
    site = Site(f.mod.file, node.line, node.col, f"{f.mod.name}/{f.name}", f.qual)
    src = pybackend.emit_main(irp, f.qual, site, contracts)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(src, encoding="utf-8")
    out.chmod(out.stat().st_mode | 0o755)


def run_examples_py(prog, modules) -> dict:
    """Compile every example of `modules` into one harness Python script and run it."""
    irp, cases = lower_examples(prog, modules)
    pybackend.check_features(irp)
    src = pybackend.emit_cases(irp, cases)
    with tempfile.TemporaryDirectory(prefix="lm-cases-py-") as tmp:
        script = Path(tmp) / "cases.py"
        script.write_text(src, encoding="utf-8")
        script.chmod(script.stat().st_mode | 0o755)
        p = subprocess.run([sys.executable, str(script)], cwd=tmp, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"example harness crashed (exit {p.returncode}):\n{p.stderr[-4000:]}")
    res = {}
    for line in p.stdout.splitlines():
        label, kind, detail = line.split("\t", 2)
        res[label] = (kind, detail)
    return res


def run_examples_go(prog, modules, go=None, keep_go=None) -> dict:
    """Compile every example of `modules` into one harness binary and run it: label -> (kind, detail)."""
    go = go or find_go()
    if go is None:
        raise BuildError(GO_MISSING, 3)
    irp, cases = lower_examples(prog, modules)
    _check_prims(irp)
    src = gobackend.emit_cases(irp, cases)
    with tempfile.TemporaryDirectory(prefix="lm-cases-") as tmp:
        d = Path(keep_go) if keep_go else Path(tmp)
        write_sources(src, d)
        exe = Path(tmp) / "cases"
        go_build(go, d, exe)
        p = subprocess.run([str(exe)], capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"example harness crashed (exit {p.returncode}):\n{p.stderr[-4000:]}")
    res = {}
    for line in p.stdout.splitlines():
        label, kind, detail = line.split("\t", 2)
        res[label] = (kind, detail)
    return res


def _parse(args):
    """-> (flags, positionals); raises BuildError(code 3) on bad usage."""
    spec = {"-o": True, "--os": True, "--arch": True, "--keep-go": True, "--no-contracts": False, "--target": True}
    flags, pos, i = {}, [], 0
    while i < len(args):
        a = args[i]
        if a.startswith("-"):
            if a not in spec:
                raise BuildError(f"unknown flag {a}", 3)
            if spec[a] and i + 1 >= len(args):
                raise BuildError(f"{a} needs a value", 3)
            flags[a] = args[i + 1] if spec[a] else True
            i += 2 if spec[a] else 1
            continue
        pos.append(a)
        i += 1
    if not pos or "." not in pos[0]:
        raise BuildError("missing MOD.FN", 3)
    target = flags.get("--target", "go")
    if target not in ("go", "py"):
        raise BuildError(f"--target must be one of go, py", 3)
    if target == "py":
        if "--os" in flags or "--arch" in flags:
            raise BuildError("--os/--arch cannot be used with --target py", 3)
        if "--keep-go" in flags:
            raise BuildError("--keep-go cannot be used with --target py", 3)
    else:
        for key, allowed in (("--os", OSES), ("--arch", ARCHES)):
            if key in flags and flags[key] not in allowed:
                raise BuildError(f"{key} must be one of {', '.join(allowed)}", 3)
    return flags, pos


def cmd_build(args, static, report) -> int:
    """`lm build MOD.FN [PATH..] [-o OUT] [--target go|py] [--os OS] [--arch ARCH] [--no-contracts] [--keep-go DIR]`."""
    import sys

    from .lower import LowerError

    try:
        flags, pos = _parse(args)
        target = flags.get("--target", "go")
        go = None
        if target == "go":
            go = find_go()
            if go is None:
                raise BuildError(GO_MISSING, 3)
        mname, fname = pos[0].split(".", 1)
        for p in pos[1:]:
            if not Path(p).exists():
                raise BuildError(f"no such path: {p}", 3)
        prog, _ = static(pos[1:], extra=[mname])
        if report(prog.diags, lambda e, w: ""):
            return 1
        if mname not in prog.modules or fname not in prog.modules[mname].fns:
            raise BuildError(f"no function `{pos[0]}`", 3)
        fn_info = prog.modules[mname].fns[fname]
        if target == "py":
            out = Path(flags.get("-o", f"{fname}.py"))
            build_py(prog, fn_info, out, "--no-contracts" not in flags)
            sys.stderr.write(f"build: wrote {out} ({out.stat().st_size // 1024} KB, python)\n")
        else:
            out = Path(flags.get("-o", mname if fname == "main" else f"{mname}-{fname}"))
            build(prog, fn_info, out, flags.get("--os"), flags.get("--arch"),
                  "--no-contracts" not in flags, flags.get("--keep-go"), go)
            target_str = f"{flags.get('--os', 'host')}/{flags.get('--arch', 'host')}"
            sys.stderr.write(f"build: wrote {out} ({out.stat().st_size // 1024} KB, {target_str})\n")
    except (BuildError, pybackend.BuildError) as ex:
        sys.stderr.write(f"lm build: {ex}\n")
        return ex.code
    except LowerError as ex:
        sys.stderr.write(f"lm build: {ex}\n")
        return 1
    return 0
