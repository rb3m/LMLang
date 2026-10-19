"""Printed vectors remain external constants and preserve type dependencies."""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from lm.build import run_examples_py
from lm.check import Checker
from lm.loader import load
from lm.runner import example_outcomes

ROOT = Path(__file__).resolve().parents[2]
SOURCE = '''(module vec-tools
  (purpose "Vector external constants and generic dependencies.")
  (export Box echo)
  (type (Box a) (rec (item a)))
  (type (Rows a) (Vec (Box (Vec a))))
  (fn echo
    (purpose "Preserve nested vectors in a generic record.")
    (sig (v (Rows Str)) -> (Rows Str))
    (example ((vecof (new Box (item (vecof "a" "b")))))
      => (vecof (new Box (item (vecof "a" "b")))))
    (body v))
  (fn contract-only
    (purpose "Keep vector runtime support for contract literals.")
    (sig -> Int)
    (ensures (= (vecof result) (vecof 1)))
    (example () => 1)
    (body 1)))
'''


class VecTooling(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.project = Path(tmp.name)
        (self.project / "src").mkdir()
        (self.project / "src/vec-tools.lm").write_text(SOURCE)

    def lm(self, *args):
        return subprocess.run(
            [sys.executable, "-m", "lm", *args], cwd=self.project,
            env={**os.environ, "PYTHONPATH": str(ROOT)},
            capture_output=True, text=True)

    def test_printed_nested_vector_round_trip(self):
        value = '(vecof (new vec-tools.Box (item (vecof "a" "b"))))'
        for value in (value, "(vecof)"):
            first = self.lm("run", "vec-tools.echo", value)
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual(first.stdout.strip(), value)
            again = self.lm("run", "vec-tools.echo", first.stdout.strip())
            self.assertEqual(again.returncode, 0, again.stderr)
            self.assertEqual(first.stdout, again.stdout)

    def test_queries_keep_vec_and_generic_dependencies(self):
        result = self.lm("slice", "vec-tools.echo")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("(type (Rows a) (Vec (Box (Vec a))))", result.stdout)
        self.assertIn("(type (Box a)", result.stdout)
        result = self.lm("explain", "vec-tools.echo")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Rows Str", result.stdout)
        result = self.lm("index")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("(Vec (Box (Vec a)))", result.stdout)

    def test_python_embeds_vectors_in_examples_and_contracts(self):
        prog = load([str(self.project / "src/vec-tools.lm")])
        Checker(prog).run()
        self.assertFalse([d for d in prog.diags if d.severity == "error"])
        expected = example_outcomes(prog, ["vec-tools"])
        self.assertEqual(run_examples_py(prog, ["vec-tools"]), expected)
