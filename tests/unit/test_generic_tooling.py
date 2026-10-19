"""Generic declarations retain their identity in source tools and erase at runtime."""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from lm.build import find_go, run_examples_go, run_examples_py
from lm.check import Checker
from lm.edit import get_at, locate
from lm.index import Index
from lm.loader import load
from lm.printer import format_text
from lm.runner import example_outcomes

ROOT = Path(__file__).resolve().parents[2]
SOURCE = '''(module generic-tools
  (purpose "Generic source tools.")
  (use list)
  (export Tree Box wrap)
  (type (Tree a) (sum Leaf (Node (left (Tree a)) (item a) (right (Tree a)))))
  (type (Box a) (sum (Packed (item a))))
  (fn make
    (purpose "Use a three-argument constructor as a function.")
    (sig -> (Tree Int))
    (example () => (Node Leaf 1 Leaf))
    (body (let ((node Node)) (node Leaf 1 Leaf))))
  (fn options
    (purpose "Use the built-in constructor as a function.")
    (sig (xs (List Int)) -> (List (Opt Int)))
    (example ((list 1 2)) => (list (Some 1) (Some 2)))
    (body (list.map xs Some)))
  (fn wrap
    (purpose "Wrap each item.")
    (sig (xs (List Int)) -> (List (Box Int)))
    (example ((list 1 2)) => (list (Packed 1) (Packed 2)))
    (body (list.map xs Packed))))
'''


class GenericTooling(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.project = Path(self.tmp.name)
        (self.project / "src").mkdir()
        self.file = self.project / "src/generic-tools.lm"
        self.file.write_text(SOURCE)

    def lm(self, *args):
        return subprocess.run(
            [sys.executable, "-m", "lm", *args], cwd=self.project,
            env={**os.environ, "PYTHONPATH": str(ROOT)},
            capture_output=True, text=True)

    def index(self):
        prog = load([str(self.file)])
        Checker(prog).run()
        errors = [d for d in prog.diags if d.severity == "error"]
        self.assertFalse(errors, errors)
        return Index(prog)

    def test_printer_round_trip_preserves_generic_head(self):
        text, diags = format_text(SOURCE)
        self.assertIsNotNone(text, diags)
        self.assertIn("(type (Tree a)", text)
        again, diags = format_text(text)
        self.assertEqual(text, again, diags)

    def test_hash_covers_declared_params(self):
        source = '''(module generic-tools
  (purpose "Parameter order changes the type meaning.")
  (type (Box a b) (rec (first a) (second b))))
'''
        self.file.write_text(source)
        before = self.index().hash("generic-tools.Box")
        self.file.write_text(source.replace("(Box a b)", "(Box b a)"))
        after = self.index().hash("generic-tools.Box")
        self.assertNotEqual(before, after)

    def test_slice_closes_recursive_generic_declaration_once(self):
        idx = self.index()
        text, items, _ = idx.slice("generic-tools.Tree")
        self.assertEqual(text.count("(type (Tree a)"), 1)
        self.assertEqual(set(items), {"generic-tools.Tree"})
        text, items, _ = idx.slice("generic-tools.wrap")
        self.assertEqual(text.count("(type (Box a)"), 1)
        self.assertIn("generic-tools.Box", items)

    def test_index_shows_generic_parameters(self):
        idx = self.index()
        lines = idx.index_lines([idx.prog.modules["generic-tools"]])
        self.assertTrue(any("generic-tools.Tree a" in line for line in lines))

    def test_slice_closes_mutual_generic_declarations_once(self):
        self.file.write_text('''(module generic-tools
  (purpose "Mutually recursive generic closure.")
  (type (First a) (sum FirstEnd (FirstNext (next (Second a)))))
  (type (Second a) (sum SecondEnd (SecondNext (next (First a))))))
''')
        text, items, _ = self.index().slice("generic-tools.First")
        self.assertEqual(text.count("(type (First a)"), 1)
        self.assertEqual(text.count("(type (Second a)"), 1)
        self.assertEqual(set(items),
                         {"generic-tools.First", "generic-tools.Second"})

    def test_type_and_variant_rename(self):
        user_file = self.project / "src/user.lm"
        user_file.write_text('''(module user
  (purpose "Use a qualified generic type.")
  (use generic-tools)
  (fn echo
    (purpose "Return its argument.")
    (sig (x (generic-tools.Box Int)) -> (generic-tools.Box Int))
    (body x)))
''')
        result = self.lm("edit", "rename", "generic-tools.Box", "Crate")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("(type (Crate a)", self.file.read_text())
        self.assertIn("(List (Crate Int))", self.file.read_text())
        self.assertIn("(generic-tools.Crate Int)", user_file.read_text())
        result = self.lm("edit", "rename", "generic-tools.Packed", "Wrapped")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("Packed", self.file.read_text())
        self.assertIn("list.map xs Wrapped", self.file.read_text())
        result = self.lm("edit", "rename", "generic-tools.Tree", "Branch")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("(type (Branch a)", self.file.read_text())
        self.assertIn("(left (Branch a))", self.file.read_text())

    def test_replace_generic_declaration_keeps_name(self):
        result = self.lm(
            "edit", "replace-decl", "generic-tools.Box",
            "(type (Box b) (sum (Packed (item b))))")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("(type (Box b)", self.file.read_text())

    def test_generic_reference_paths_are_addressable(self):
        prog = self.index().prog
        for (mn, path), target in prog.refs.items():
            if mn != "generic-tools":
                continue
            node = get_at(prog.modules[mn].root,
                          locate(prog.modules[mn].root, path.split("/")))
            self.assertIsNotNone(node, (path, target))

    def test_explain_type_shows_params(self):
        result = self.lm("explain", "generic-tools.Tree")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Parameters: a", result.stdout)
        self.assertIn("(Tree a)", result.stdout)

    def test_generic_constructor_differential(self):
        prog = self.index().prog
        expected = example_outcomes(prog, ["generic-tools"])
        self.assertTrue(expected)
        self.assertEqual(run_examples_py(prog, ["generic-tools"]), expected)
        if find_go() is None:
            sys.stderr.write("\nSKIP: Go unavailable; generic Go differential not run\n")
            self.skipTest("Go unavailable")
        self.assertEqual(run_examples_go(prog, ["generic-tools"]), expected)
