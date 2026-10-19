"""Executable generic programs and external instantiated values."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from lm import accept
from lm.build import find_go, lower_examples, run_examples_go
from lm.check import Checker
from lm.loader import load
from lm.pybackend import emit_cases
from lm.runner import example_outcomes
from lm.sexpr import read


ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests/spec/check"
PROGRAMS = [str(FIXTURES / f"{name}.lm") for name in (
    "generic-tree", "generic-values", "generic-key-good",
)]


def checked_program(test):
    prog = load(PROGRAMS)
    Checker(prog).run()
    test.assertEqual([d.to_json() for d in prog.diags
                      if d.severity == "error"], [])
    return prog


class GenericPrograms(unittest.TestCase):
    def test_interpreted_examples(self):
        prog = checked_program(self)
        outcomes = example_outcomes(prog, prog.targets)
        self.assertGreaterEqual(len(outcomes), 12)
        self.assertEqual({kind for kind, _ in outcomes.values()}, {"ok"})
        self.assertEqual(outcomes["generic-tree/fold/example#0"],
                         ("ok", "6"))

    def test_python_matches_interpreter(self):
        prog = checked_program(self)
        want = example_outcomes(prog, prog.targets)
        irp, cases = lower_examples(prog, prog.targets)
        with tempfile.TemporaryDirectory(prefix="lm-generics-py-") as tmp:
            script = Path(tmp) / "cases.py"
            script.write_text(emit_cases(irp, cases), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(script)], cwd=tmp,
                capture_output=True, text=True, check=False,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        got = {}
        for line in result.stdout.splitlines():
            label, kind, detail = line.split("\t", 2)
            got[label] = (kind, detail)
        self.assertEqual(got, want)

    def test_go_matches_interpreter(self):
        if find_go() is None:
            sys.stderr.write("\nSKIP: Go toolchain not found; generic "
                             "differential tests NOT run\n")
            self.skipTest("go not found: generic differential not run")
        prog = checked_program(self)
        self.assertEqual(run_examples_go(prog, prog.targets),
                         example_outcomes(prog, prog.targets))


class GenericExternalValues(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="lm-generic-scenario-")
        self.addCleanup(self.tmp.cleanup)
        self.project = Path(self.tmp.name)
        (self.project / "src").mkdir()
        self.source = self.project / "src/boxes.lm"
        self.source.write_text('''(module boxes
  (purpose "Generic external values.")
  (export Tree Box Keyed tree boxed empty keyed)
  (type (Tree a) (sum Leaf (Node (value a))))
  (type (Box a) (rec (item a)))
  (type (Keyed a) (sum Vacant (Stored (value a) (items (Map a Int)))))
  (fn boxed
    (purpose "Return a boxed integer.")
    (sig (value (Box Int)) -> (Box Int))
    (example ((new Box (item 3))) => (new Box (item 3)))
    (body value))
  (fn empty
    (purpose "Return an empty tree.")
    (sig (value (Tree Int)) -> (Tree Int))
    (example (Leaf) => Leaf)
    (body value))
  (fn tree
    (purpose "Return a tree of integers.")
    (sig (value (Tree Int)) -> (Tree Int))
    (example ((Node 3)) => (Node 3))
    (body value))
  (fn keyed
    (purpose "Return an empty value with a key-constrained argument.")
    (sig -> (Keyed a))
    (example () => Vacant)
    (body Vacant)))
''', encoding="utf-8")
        result = self.command("fmt", str(self.source))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def command(self, *args):
        return subprocess.run(
            [sys.executable, "-m", "lm", *args], cwd=self.project,
            env={**os.environ, "PYTHONPATH": str(ROOT)},
            capture_output=True, text=True, check=False,
        )

    def test_scenarios_with_generic_arguments_and_expectations(self):
        prog = load([str(self.source)])
        ck = Checker(prog)
        ck.run()
        self.assertEqual([d.to_json() for d in prog.diags
                          if d.severity == "error"], [])
        for name, value in (
            ("tree", "(boxes.Node 3)"),
            ("empty", "boxes.Leaf"),
            ("boxed", "(new boxes.Box (item 3))"),
        ):
            node, diags = read(
                f'(scenario "{name}" (status proposed) (why "Generic value.") '
                f'(run boxes.{name} {value}) (expect {value}))',
                "<generic-scenario>",
            )
            self.assertEqual(diags, [])
            scenario = accept.Scenario(node, "<generic-scenario>")
            self.assertEqual(accept.execute(prog, ck, scenario), (True, ""))

    def test_run_checks_instantiated_and_nullary_variants(self):
        for name, value, expected in (
            ("tree", "(boxes.Node 3)", "(boxes.Node 3)\n"),
            ("empty", "boxes.Leaf", "boxes.Leaf\n"),
            ("boxed", "(new boxes.Box (item 3))",
             "(new boxes.Box (item 3))\n"),
        ):
            result = self.command("run", f"boxes.{name}", value)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(result.stdout, expected)
        result = self.command("run", "boxes.tree", '(boxes.Node "wrong")')
        self.assertEqual(result.returncode, 1, result.stderr)
        codes = [json.loads(line)["code"]
                 for line in result.stdout.splitlines()]
        self.assertIn("E-TYPE", codes)

    def test_scenario_expectation_checks_key_constraints(self):
        prog = load([str(self.source)])
        ck = Checker(prog)
        ck.run()
        self.assertEqual([d.to_json() for d in prog.diags
                          if d.severity == "error"], [])
        node, diags = read(
            '(scenario "Bad generic key" (status proposed) '
            '(why "Lists cannot become map keys in an expected value.") '
            '(run boxes.keyed) '
            '(expect (boxes.Stored (list 1) (mapof))))',
            "<generic-scenario>",
        )
        self.assertEqual(diags, [])
        prepared, problem = accept.validate(
            prog, ck, accept.Scenario(node, "<generic-scenario>"),
        )
        self.assertIsNone(prepared)
        self.assertIn("does not type-check", problem)
        self.assertIn("Map keys and Set elements", problem)
