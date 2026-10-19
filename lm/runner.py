"""`lm test` and `lm run`: execute checked programs and report runtime diagnostics."""
from __future__ import annotations

import sys
import threading

from .diag import make
from .interp import Interp
from .resolve import head
from .rand_prims import SplitMix64
from .values import LmFail, Denied, Overflow, ProofViolation, Violation, show, show_args

# Runtime faults: program bugs, not reported failures. `lm run` exits FAULT_EXIT for them (ADR-031 item 3).
FAULT_CODES = frozenset(["E-OVERFLOW", "E-FLOAT", "E-RECURSION-LIMIT", "E-REQUIRES-VIOLATED", "E-ENSURES-VIOLATED", "E-PROOF-VIOLATED"])
FAULT_EXIT = 70  # EX_SOFTWARE


def in_big_stack(fn):
    """Give non-tail LM recursion room to raise RecursionError rather than crash.

    Self tail calls run inside Interp.call_fn's loop and consume no extra stack.
    """
    box: dict = {}

    def target():
        try:
            box["r"] = fn()
        except BaseException as ex:  # re-raised in caller
            box["e"] = ex

    old = sys.getrecursionlimit()
    try:
        threading.stack_size(512 * 1024 * 1024)
        sys.setrecursionlimit(150000)
    except (ValueError, RuntimeError):
        sys.setrecursionlimit(8000)
    t = threading.Thread(target=target)
    t.start()
    t.join()
    sys.setrecursionlimit(old)
    if "e" in box:
        raise box["e"]
    return box["r"]


def runtime_diag(ex, context="", it=None):
    """Map a runtime exception to a Diagnostic (or None if it is not a user-program fault).
    `it` is the Interp that raised it; E-OVERFLOW reads its frame stack."""
    if isinstance(ex, Overflow):
        from .fault import overflow_diag
        return overflow_diag(ex, it)
    if isinstance(ex, Violation):
        f = ex.fn
        return make(ex.code, f.mod.file, ex.node.line, ex.node.col,
                    f"{ex.node.items[0].value} of {f.qual} is false for arguments {show_args(ex.args_)}{context}",
                    path=f"{f.mod.name}/{f.name}/{ex.clause}", found=show_args(ex.args_))
    if isinstance(ex, ProofViolation):
        return make("E-PROOF-VIOLATED", ex.file, ex.line, ex.col,
                    f"discharged operation at {ex.path} violated", path=ex.path)
    if isinstance(ex, Denied):
        f = ex.fn
        return make("E-EFFECT-DENIED", f.mod.file, f.node.line, f.node.col,
                    f"{f.qual} needs effect `{ex.eff}`; run with --allow {ex.eff}", path=f"{f.mod.name}/{f.name}",
                    expected=f"--allow {ex.eff}", found=ex.eff)
    if isinstance(ex, RecursionError):
        return make("E-RECURSION-LIMIT", "", 1, 1, f"recursion limit reached{context}")
    return None


def test_program(prog):
    """Run every example of every target module. Returns (diagnostics, stats)."""
    from .check_types import contains_opaque
    from .types import fn

    diags, stats = [], {"examples": 0, "failed": 0, "no_examples": []}

    def go():
        for mn in prog.targets:
            m = prog.modules[mn]
            for f in (m.fns[n] for n in sorted(m.fns)):
                exs = f.clauses.get("example", [])
                if not exs:
                    signature = fn([t for _, t in f.params], f.ret)
                    if not f.eff and not contains_opaque(
                            signature, "pat.Pat", prog.type_index):
                        stats["no_examples"].append(f.qual)
                    continue
                for k, c in enumerate(exs):
                    stats["examples"] += 1
                    d = _example(prog, f, k, c)
                    if d is not None:
                        stats["failed"] += 1
                        diags.append(d)

    in_big_stack(go)
    from .runtime_cases import fixture_cases, fixture_outcomes
    outcomes = fixture_outcomes(prog, prog.targets)
    stats['cases'] = len(outcomes)
    for label, f, want in fixture_cases(prog, prog.targets):
        if outcomes[label] != want:
            stats['failed'] += 1
            diags.append(make('E-EXAMPLE-FAILED', f.mod.file, f.node.line, f.node.col,
                              f'{label}: expected {want}, found {outcomes[label]}', path=label))
    return diags, stats


def _example(prog, f, k, c):
    from .examples import clause_values, example_parts
    from .fake_world import FakeWorld

    path = f"{f.mod.name}/{f.name}/example#{k}"
    m = f.mod
    parts = example_parts(c)
    world = None
    if parts.given is not None:
        clauses = [(head(clause), tuple(clause_values(prog, m, clause)))
                   for clause in parts.given.items[1:]]
        world = FakeWorld(clauses)
    it = Interp(prog, allowed=f.eff, contracts=True, seed=0, world=world)
    exp = parts.result
    try:
        args = [it.ev(a, {}, m) for a in parts.args.items]
        try:
            got, failed = it.call_fn(f, args), None
        except LmFail as x:
            got, failed = None, x
        found = (f"(fail {failed.id}"
                 + "".join(" " + show(a) for a in failed.args_) + ")"
                 if failed else show(got))
        if head(exp) == "fail":
            want = it.fail_value(exp, {}, m)
            expected = f"(fail {want.id}" + "".join(" " + show(a) for a in want.args_) + ")"
            matched = (failed is not None
                       and (failed.id, failed.args_) == (want.id, want.args_))
        else:
            want = it.ev(exp, {}, m)
            expected = show(want)
            matched = failed is None and got == want and type(got) is type(want)
        mismatches = [] if matched else [(expected, found)]
        if world is not None:
            mismatches.extend(_world_checks(prog, f, parts, world))
        if not mismatches:
            return None
        expected, found = mismatches[0]
        detail = "; ".join(f"expected {want}, found {got}"
                           for want, got in mismatches)
        return make("E-EXAMPLE-FAILED", m.file, c.line, c.col,
                    f"{f.qual}{show_args(args)}: {detail}", path=path,
                    expected=expected, found=found)
    except (Violation, Denied, RecursionError, Overflow, ProofViolation) as ex:
        d = runtime_diag(ex, context=f" (in {path})", it=it)
        if d.file == "":
            d.file, d.line, d.col, d.path = m.file, c.line, c.col, path
        return d


def _world_checks(prog, f, parts, world):
    from .examples import clause_values

    mismatches, streams = [], set()
    for _, clause in parts.checks:
        name = head(clause)
        values = clause_values(prog, f.mod, clause)
        if name in ("out", "err"):
            streams.add(name)
            got = getattr(world, name).getvalue()
            if got != values[0]:
                mismatches.append((f"{name} {show(values[0])}",
                                   f"{name} {show(got)}"))
            continue
        path = values[0]
        is_file, is_dir = path in world.files, path in world.dirs
        matched = {
            "file": is_file and world.files.get(path) == values[-1],
            "no-file": not is_file,
            "dir": is_dir,
            "no-dir": not is_dir,
        }[name]
        if matched:
            continue
        expected = "(" + name + " " + " ".join(show(v) for v in values) + ")"
        found = ("(file " + show(path) + " " + show(world.files[path]) + ")"
                 if is_file else "(dir " + show(path) + ")" if is_dir
                 else "absent " + show(path))
        mismatches.append((expected, found))
    if "io.out" in f.eff:
        for name in ("out", "err"):
            if name in streams:
                continue
            got = getattr(world, name).getvalue()
            if got:
                mismatches.append((f'{name} ""', f"{name} {show(got)}"))
    return mismatches


def example_outcomes(prog, modules) -> dict:
    """Interpreter outcome of every example of `modules`: label -> (kind, detail), the format of the
    compiled harness (lm/build.py run_examples_go): ok + value, fail + (fail ..), fault + code."""
    it = Interp(prog, allowed=(), contracts=True)
    res: dict = {}

    def one(f, c):
        it.reset()
        it.rng = SplitMix64(0)
        args = [it.ev(a, {}, f.mod) for a in c.items[1].items]
        try:
            return "ok", show(it.call_fn(f, args))
        except LmFail as x:
            return "fail", f"(fail {x.id}" + "".join(" " + show(a) for a in x.args_) + ")"
        except (Violation, Denied, RecursionError, Overflow, ProofViolation) as ex:
            return "fault", runtime_diag(ex, it=it).code

    def go():
        for mn in modules:
            m = prog.modules[mn]
            for name in sorted(m.fns):
                if m.fns[name].eff:
                    continue
                for k, c in enumerate(m.fns[name].clauses.get("example", [])):
                    res[f"{mn}/{name}/example#{k}"] = one(m.fns[name], c)

    in_big_stack(go)
    from .runtime_cases import fixture_outcomes
    res.update(fixture_outcomes(prog, modules))
    return res
