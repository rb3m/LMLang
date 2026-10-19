"""Example syntax, types and constant fake-world metadata (SPEC 5/12)."""
from __future__ import annotations

from dataclasses import dataclass

from .check_pat import check_external_type
from .fake_world import parent_path, valid_path
from .resolve import head
from .sexpr import Atom, SList
from .types import INT, STR
from .values import (Denied, LmFail, Overflow, ProofViolation, Violation,
                     in_range)


@dataclass(frozen=True)
class ExampleParts:
    args: SList
    given: SList | None
    result: object
    result_index: int
    checks: tuple


def clause_name(node):
    if (isinstance(node, SList) and node.items
            and isinstance(node.items[0], Atom)
            and node.items[0].kind == "sym"):
        return node.items[0].value
    return None


def example_parts(clause):
    """Read either example form, preserving source indices for refs/edits."""
    items = clause.items
    if len(items) < 4 or not isinstance(items[1], SList):
        return None
    given = items[2] if clause_name(items[2]) == "given" else None
    arrow = 3 if given is not None else 2
    if len(items) <= arrow + 1:
        return None
    token = items[arrow]
    if not (isinstance(token, Atom) and token.kind == "sym"
            and token.value == "=>"):
        return None
    return ExampleParts(items[1], given, items[arrow + 1], arrow + 1,
                        tuple(enumerate(items[arrow + 2:], arrow + 2)))


def check_example(ck, m, f, clause, path):
    if 'net.http' in f.eff:
        ck.diag(m, "E-EXAMPLE", clause, path,
                "network mocking is not supported yet")
        return
    parts = example_parts(clause)
    if parts is None:
        ck.diag(m, "E-EXAMPLE" if f.eff else "E-PARSE", clause, path,
                "expected (example (args...) [given] => result [checks...])")
        return
    if bool(f.eff) != (parts.given is not None) or (
            not f.eff and parts.checks):
        ck.diag(m, "E-EXAMPLE", clause, path,
                "effectful examples require (given ...); "
                "pure examples cannot have given or checks")
        return
    args = parts.args.items
    if not ck.arity(m, f"fn `{f.name}`", len(f.params), len(args),
                    clause, path):
        return
    ft = ck.fn_type(f)
    ck.note_keys(ft, clause, path)

    def run():
        for i, (arg, pt) in enumerate(zip(args, ft[1])):
            ap = f"{path}/1/{i}"
            at = ck.infer(m, arg, {}, ap)
            ck.expect(m, pt, at, arg, ap,
                      "example argument")
            check_external_type(ck, m, at, arg, ap)
        exp, ep = parts.result, f"{path}/{parts.result_index}"
        if head(exp) == "fail":
            err = ck.fail_check(m, exp, {}, ep)
            if err is not None and err.id not in f.fails:
                ck.diag(m, "E-FAILS-UNDECLARED", exp, ep,
                        f"example expects undeclared failure `{err.id}`",
                        found=err.id)
            if err is not None:
                fields = zip(exp.items[2:], err.fields)
                for i, (arg, (_, t)) in enumerate(fields, 2):
                    check_external_type(ck, m, t, arg, f"{ep}/{i}")
        else:
            et = ck.infer(m, exp, {}, ep)
            ck.expect(m, ft[2], et, exp, ep,
                      "example result")
            check_external_type(ck, m, et, exp, ep)

    ck.sandbox(m, "an example", run)
    ck.check_eq(m)
    if parts.given is not None:
        MetadataChecks(ck, m, f, path).check(parts)


GIVEN = {"args": None, "stdin": 1, "env": 2, "file": 2, "dir": 1,
         "now-ms": 1, "seed": 1}
CHECKS = {"out": 1, "err": 1, "file": 2, "no-file": 1,
          "dir": 1, "no-dir": 1}
FS = {"fs.read", "fs.write", "fs.delete"}
EFFECTS = {"args": {"io.in"}, "stdin": {"io.in"}, "env": {"env.read"},
           "out": {"io.out"}, "err": {"io.out"},
           "now-ms": {"time.now"}, "seed": {"rand"}}


def clause_values(prog, m, clause):
    """Evaluate checked closed expressions with a bounded pure evaluator."""
    from .consts import ConstEvaluator

    it = ConstEvaluator(prog)
    return tuple(it.ev(value, {}, m) for value in clause.items[1:])


class MetadataChecks:
    def __init__(self, ck, m, f, path):
        self.ck, self.m, self.f, self.path = ck, m, f, path

    def error(self, clause, path, message):
        self.ck.diag(self.m, "E-EXAMPLE", clause, path, message)

    def check(self, parts):
        given = [(f"{self.path}/2/{i}", c)
                 for i, c in enumerate(parts.given.items[1:], 1)]
        checks = [(f"{self.path}/{i}", c) for i, c in parts.checks]
        rows = []
        for is_given, clauses in ((True, given), (False, checks)):
            singles = set()
            for path, clause in clauses:
                name = clause_name(clause)
                arities = GIVEN if is_given else CHECKS
                if name not in arities:
                    self.error(clause, path, "unknown example clause")
                    continue
                arity = arities[name]
                if arity is not None and len(clause.items) != arity + 1:
                    self.error(clause, path, f"{name} takes {arity} value(s)")
                    continue
                effects = EFFECTS.get(
                    name, FS if is_given else FS - {"fs.read"})
                if not effects & self.f.eff:
                    self.error(clause, path,
                               f"{name} needs a declared effect from "
                               + ", ".join(sorted(effects)))
                if name in ("args", "stdin", "now-ms", "seed", "out", "err"):
                    if name in singles:
                        self.error(clause, path, f"duplicate {name} clause")
                    singles.add(name)
                if self.types(clause, path, name):
                    rows.append((is_given, path, clause))
        # Never interpret metadata in a program with unchecked/invalid bodies.
        if any(d.severity == "error" for d in self.ck.prog.diags):
            return
        self.values(rows)

    def types(self, clause, path, name):
        ck, m = self.ck, self.m
        start = len(ck.prog.diags)

        def run():
            for i, value in enumerate(clause.items[1:], 1):
                vp = f"{path}/{i}"
                want = INT if name in ("now-ms", "seed") else STR
                ck.expect(m, want, ck.infer(m, value, {}, vp), value, vp,
                          "example clause")

        ck.sandbox(m, "an example clause", run)
        ck.check_eq(m)
        diags = ck.prog.diags[start:]
        del ck.prog.diags[start:]
        for d in diags:
            self.error(clause, d.path, d.msg)
        return not diags

    def values(self, rows):
        from .consts import ConstBudgetExhausted, ConstEvalError

        env, tree, checks = set(), {}, {}
        for is_given, path, clause in rows:
            name = head(clause)
            try:
                vals = clause_values(self.ck.prog, self.m, clause)
            except (ConstBudgetExhausted, ConstEvalError, LmFail, Denied,
                    Overflow, ProofViolation, Violation, RecursionError):
                self.error(clause, path, "example clause must be constant "
                           "and evaluate without failure or fault")
                continue
            if name in ("now-ms", "seed"):
                if type(vals[0]) is not int or not in_range(vals[0]):
                    self.error(clause, path, f"{name} must fit signed Int64")
                continue
            if name == "env":
                if vals[0] in env:
                    self.error(clause, path, "duplicate environment key")
                env.add(vals[0])
                continue
            if name not in ("file", "dir", "no-file", "no-dir"):
                continue
            target = vals[0]
            if not valid_path(target):
                self.error(clause, path, "invalid fake filesystem path")
                continue
            if is_given:
                if target in tree or (target == "/" and name == "file"):
                    self.error(clause, path,
                               "duplicate or conflicting path declaration")
                tree[target] = (name, clause, path)
                continue
            previous = checks.setdefault(target, [])
            for old_name, old_vals in previous:
                if contradictory(name, vals, old_name, old_vals):
                    self.error(clause, path, "contradictory filesystem checks")
                    break
            previous.append((name, vals))
        for target, (_, clause, path) in tree.items():
            parent = parent_path(target)
            if parent not in (None, ".", "/") and (
                    parent not in tree or tree[parent][0] != "dir"):
                self.error(clause, path, "parent directory must be declared")


def contradictory(name, vals, old_name, old_vals):
    if name == old_name:
        return name == "file" and vals[1] != old_vals[1]
    return frozenset((name, old_name)) in (
        {"file", "no-file"}, {"dir", "no-dir"}, {"file", "dir"})
