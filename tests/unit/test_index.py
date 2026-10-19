import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from golden_support import golden_command

from lm.check import Checker
from lm.index import Index, tokens
from lm.loader import load

ROOT = Path(__file__).resolve().parents[2]
GOLDEN = ROOT / "tests/golden"

LIB = '''(module lib
  (purpose "p")
  (export Cents shown)
  (type Cents Int)
  (fn helper
    (purpose "p")
    (sig (x Int) -> Int)
    (body x))
  (fn shown
    (purpose "p")
    (sig (x Cents) -> Cents)
    (requires (>= x 0))
    (ensures (>= result 0))
    (example (1) => 1)
    (body (helper x))))
'''
APP = '''(module app
  (purpose "p")
  (use lib)
  (fn f
    (purpose "p")
    (sig (x Int) -> Int)
    (body (lib.shown x)))
  (fn g
    (purpose "p")
    (sig (x Int) -> Int)
    (body (+ x 1))))
'''
OTHER = '''(module other
  (purpose "p")
  (fn h
    (purpose "p")
    (sig (x Int) -> Int)
    (body x)))
'''


def build(files):
    d = tempfile.mkdtemp()
    for n, t in files.items():
        (Path(d) / f"{n}.lm").write_text(t)
    prog = load([d])
    ck = Checker(prog)
    ck.check_all = True
    ck.run()
    assert not [x for x in prog.diags if x.severity == "error"], [x.to_json() for x in prog.diags]
    return Index(prog)


def slice_of(files, sym, **kw):
    return build(files).slice(sym, **kw)[0]


class SliceSufficiency(unittest.TestCase):
    base = {"lib": LIB, "app": APP, "other": OTHER}

    def mut(self, name, old, new):
        files = dict(self.base)
        assert old in files[name]
        files[name] = files[name].replace(old, new)
        return files

    def test_edits_outside_slice_do_not_change_it(self):
        want = slice_of(self.base, "app.f")
        for name, old, new in [
            ("lib", "(body (helper x))", "(body (+ (helper x) 0))"),  # callee body (signature-only slice)
            ("lib", "(example (1) => 1)", "(example (2) => 2)"),  # callee example
            ("lib", "(body x))\n  (fn shown", "(body (+ x 1)))\n  (fn shown"),  # unrelated private helper
            ("app", "(body (+ x 1))", "(body (+ x 2))"),  # sibling fn
            ("other", "(body x)", "(body (+ x 1))"),  # other module
        ]:
            self.assertEqual(slice_of(self.mut(name, old, new), "app.f"), want, (name, old))

    def test_edits_inside_slice_change_it(self):
        want = slice_of(self.base, "app.f")
        for name, old, new in [
            ("app", "(body (lib.shown x))", "(body (lib.shown (+ x 1)))"),  # root body
            ("lib", "(sig (x Cents) -> Cents)", "(sig (x Int) -> Int)"),  # callee signature
            ("lib", "(requires (>= x 0))", "(requires (> x 0))"),  # callee precondition (ADR-028)
            ("lib", "(ensures (>= result 0))", "(ensures (> result 0))"),  # callee postcondition (ADR-028)
            ("lib", '(purpose "p")\n  (export', '(purpose "q")\n  (export'),  # module purpose appears in the slice
        ]:
            self.assertNotEqual(slice_of(self.mut(name, old, new), "app.f"), want, (name, old))

    def test_callee_contract_types_are_in_slice(self):
        lib = """(module lib
  (purpose "p")
  (export run)
  (type Mode (sum On Off))
  (fn run
    (purpose "p")
    (sig (m Int) -> Int)
    (requires (or (> m 0) (= On Off)))
    (example (1) => 0)
    (body 0)))
"""
        app = """(module app
  (purpose "p")
  (use lib)
  (fn f
    (purpose "p")
    (sig -> Int)
    (body (lib.run 1))))
"""
        text = slice_of({"lib": lib, "app": app}, "app.f")
        self.assertIn("(requires (or (> m 0) (= On Off)))", text)
        self.assertIn("(type Mode (sum On Off))", text)  # reachable only through the contract
        self.assertNotIn("(example", text)

    def test_bodies_and_depth(self):
        base = slice_of(self.base, "app.f", bodies=True, depth=1)
        self.assertIn("(body (helper x))", base)
        self.assertNotIn("(fn helper", base)
        deep = slice_of(self.base, "app.f", bodies=True, depth=2)
        self.assertIn("(fn helper", deep)
        changed = slice_of(self.mut("lib", "(body (helper x))", "(body (+ (helper x) 0))"), "app.f", bodies=True)
        self.assertNotEqual(changed, base)

    def test_callers_deps(self):
        idx = build(self.base)
        self.assertEqual([o for o, _ in idx.callers("lib.shown")], ["app.f"])
        self.assertEqual(idx.callers("lib.helper")[0][0], "lib.shown")
        self.assertEqual(idx.deps("app.f", 2), [(  "lib.shown", 1), ("lib.Cents", 2), ("lib.helper", 2)])

    def test_hash_ignores_purpose_and_examples_only(self):
        h = build(self.base).hash("lib.shown")
        same = build(self.mut("lib", "(example (1) => 1)", "(example (2) => 2)")).hash("lib.shown")
        self.assertEqual(h, same)
        for old, new in [("(body (helper x))", "(body (helper (helper x)))"), ("(sig (x Cents) -> Cents)", "(sig (x Int) -> Cents)")]:
            self.assertNotEqual(build(self.mut("lib", old, new)).hash("lib.shown"), h)

    def test_budget_drops_deepest_first_and_keeps_root(self):
        idx = build(self.base)
        full, items, _ = idx.slice("app.f")
        text, kept, dropped = idx.slice("app.f", budget=tokens(full) - 1)
        self.assertEqual(dropped, ["lib.Cents", "lib.shown"] if "lib.Cents" in items else ["lib.shown"])
        self.assertIn("app.f", kept)
        self.assertLessEqual(tokens(text), tokens(full))


class GoldenOutputs(unittest.TestCase):
    CASES = {
        "index-examples": ["index", "examples"],
        "index-stdlib": ["index", "examples", "--stdlib", "--exported"],
        "slice-billing-total": ["slice", "billing.total"],
        "slice-list-sum-bodies": ["slice", "list.sum", "--bodies"],
        "slice-shapes-scale": ["slice", "shapes.scale"],
        "slice-shapes-shape-type": ["slice", "shapes.Circle"],
        "callers-list-sum": ["callers", "list.sum", "examples"],
        "deps-billing-total": ["deps", "billing.total", "--depth", "2"],
        "hash-billing-total": ["hash", "billing.total"],
    }

    def test_golden(self):
        for name, args in self.CASES.items():
            p = golden_command(args)
            self.assertEqual(p.returncode, 0, (name, p.stderr))
            f = GOLDEN / f"{name}.txt"
            if os.environ.get("UPDATE_GOLDEN"):
                f.write_text(p.stdout)
            self.assertEqual(p.stdout, f.read_text(), name)

    def test_goldens_ignore_src(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("examples", "stdlib"):
                (root / name).symlink_to(ROOT / name, target_is_directory=True)
            (root / "src").mkdir()
            # Even a duplicate, malformed module must not affect golden queries.
            (root / "src/billing.lm").write_text("(broken")
            for name, args in self.CASES.items():
                with self.subTest(command=name):
                    result = golden_command(args, root)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertNotIn("error(s)", result.stderr)
                    self.assertEqual(result.stdout, (GOLDEN / f"{name}.txt").read_text())

    def test_errors(self):
        for args in (["slice"], ["slice", "nodot"], ["slice", "billing.nope"], ["slice", "x.y", "--bogus"], ["deps"], ["hash", "zzz.q"]):
            p = subprocess.run([sys.executable, "-m", "lm", *args], cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(p.returncode, 3, args)


class ExportMarksInIndex(unittest.TestCase):
    def test_export_marks_in_index(self):
        mod_default = """(module mod-default
  (purpose "Default exports.")
  (type Color (sum Red Blue))
  (error BadVal (code Int))
  (const max-n (purpose "Max.") (type Int) (value 10))
  (fn inc
    (purpose "Increment.")
    (sig (x Int) -> Int)
    (example (1) => 2)
    (body (+ x 1))))
"""
        mod_empty = """(module mod-empty
  (purpose "Empty exports.")
  (export)
  (type Secret Int)
  (error SecretErr (msg Str))
  (const hidden-c (purpose "Hidden.") (type Int) (value 42))
  (fn hidden-fn
    (purpose "Hidden.")
    (sig (x Int) -> Int)
    (body x)))
"""
        mod_explicit = """(module mod-explicit
  (purpose "Explicit exports.")
  (export Shown inc)
  (type Hidden Int)
  (type Shown (sum On Off))
  (const hidden-c (purpose "Hidden.") (type Int) (value 42))
  (fn inc
    (purpose "Increment.")
    (sig (x Int) -> Int)
    (example (1) => 2)
    (body (+ x 1)))
  (fn helper
    (purpose "Helper.")
    (sig (x Int) -> Int)
    (body x)))
"""
        idx = build({"mod-default": mod_default, "mod-empty": mod_empty, "mod-explicit": mod_explicit})
        lines_default = idx.index_lines([idx.prog.modules["mod-default"]])
        decl_lines_default = [line for line in lines_default if not line.startswith("module ")]
        self.assertTrue(all(line.startswith("*") for line in decl_lines_default))
        self.assertEqual(len(decl_lines_default), 4)

        lines_empty = idx.index_lines([idx.prog.modules["mod-empty"]])
        decl_lines_empty = [line for line in lines_empty if not line.startswith("module ")]
        self.assertTrue(all(line.startswith(" ") for line in decl_lines_empty))
        self.assertEqual(len(decl_lines_empty), 4)

        lines_explicit = idx.index_lines([idx.prog.modules["mod-explicit"]])
        decl_lines_explicit = [line for line in lines_explicit if not line.startswith("module ")]
        exported_explicit = [line for line in decl_lines_explicit if line.startswith("*")]
        unexported_explicit = [line for line in decl_lines_explicit if line.startswith(" ")]
        self.assertEqual({line.split()[1] for line in exported_explicit}, {"mod-explicit.Shown", "mod-explicit.inc"})
        self.assertEqual({line.split()[1] for line in unexported_explicit}, {"mod-explicit.Hidden", "mod-explicit.hidden-c", "mod-explicit.helper"})


if __name__ == "__main__":
    unittest.main()
