"""Pattern proof sites, diagnostics and opaque external-value boundaries."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from lm.build import find_go, run_examples_go, run_examples_py
from lm.check import Checker
from lm.interp import Interp
from lm.loader import load
from lm.lower import lower
from lm.pat_compile import PatternError
from lm.values import Named, ProofViolation

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "tests/spec/check"


class PatternChecks(unittest.TestCase):
    def checked(self, name):
        prog = load([str(CHECK / f"{name}.lm")])
        Checker(prog).run()
        return prog

    def test_literal_diagnostic_contains_scalar_position_and_reason(self):
        prog = self.checked("pat-literal-invalid")
        diag, = [d for d in prog.diags if d.code == "E-PATTERN"]
        self.assertEqual(diag.data, {"pos": 0, "reason": "unclosed class"})
        self.assertEqual(diag.path, "pat-literal-invalid/probe/body/1")

    def test_valid_literal_keeps_a_runtime_proof_guard(self):
        prog = self.checked("pat-literal-valid")
        self.assertEqual(prog.diags, [])
        self.assertEqual(len(prog.discharged), 1)
        function = prog.modules["pat-literal-valid"].fns["probe"]
        # Force an impossible compiler failure after checking to exercise the
        # invariant guard, rather than removing it as an optimization.
        with patch("lm.pat_prims.compile_pattern",
                   side_effect=PatternError(0, "program limit")):
            with self.assertRaises(ProofViolation) as raised:
                Interp(prog).apply(Named(function), [])
        self.assertEqual(raised.exception.path,
                         "pat-literal-valid/probe/body/1")

    def test_all_compile_error_vectors_match_literal_diagnostics(self):
        path = ROOT / "tests/spec/pat/vectors.json"
        vectors = json.loads(path.read_text())
        from lm.printer import escape_str

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "badpattern.lm"
            for case in vectors:
                if case["op"] != "compile-error":
                    continue
                source = escape_str(case["pattern"])
                path.write_text(
                    '(module badpattern (purpose "Literal errors.") (use pat) '
                    '(fn probe (purpose "Compile.") (sig -> pat.Pat) '
                    f'(body (pat.compile {source}))))')
                prog = load([str(path)])
                Checker(prog).run()
                errors = [d for d in prog.diags if d.code == "E-PATTERN"]
                self.assertEqual(len(errors), 1, case)
                self.assertEqual(errors[0].data, case["expected"], case)

    def test_compiled_literal_sites_keep_the_fault_guard(self):
        prog = self.checked("pat-literal-valid")
        function = "pat-literal-valid.probe"
        lowered = lower(prog, [function])
        call = lowered.fns[function].body
        self.assertTrue(call.discharged)
        # Corrupt the checked literal only in IR to test the unreachable guard
        # in each standalone runtime, retaining the original source site.
        call.args[0].value = "["
        cases = [("proof", function, [])]
        expected = {"proof": ("fault", "E-PROOF-VIOLATED")}
        with patch("lm.build.lower_examples", return_value=(lowered, cases)):
            self.assertEqual(run_examples_py(prog, prog.targets), expected)
            if find_go() is None:
                sys.stderr.write("\nSKIP: Go pattern proof guard omitted\n")
                return
            self.assertEqual(run_examples_go(prog, prog.targets), expected)

    def test_external_arguments_reject_patterns_transitively(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "src").mkdir()
            source = CHECK / "pat-external-values.lm"
            (root / "src" / source.name).write_text(source.read_text())
            cases = [
                ("direct", "pat-external-values.pattern"),
                ("direct", '(pat.compile "a")'),
                ("nested", "pat-external-values.wrapped"),
                ("nested", '(new pat-external-values.Box (items (list)))'),
                ("empty", "(list)"),
            ]
            for function, value in cases:
                with self.subTest(function=function, value=value):
                    result = subprocess.run(
                        [sys.executable, "-m", "lm", "run",
                         f"pat-external-values.{function}", value],
                        cwd=root, env={**os.environ, "PYTHONPATH": str(ROOT)},
                        capture_output=True, text=True)
                    self.assertEqual(result.returncode, 1, result.stderr)
                    self.assertEqual(result.stdout, "")
                    diags = [json.loads(line)
                             for line in result.stderr.splitlines()]
                    self.assertTrue(any(
                        d["code"] == "E-TYPE" and d["file"] == "<arg>"
                        and "cannot contain Pat" in d["msg"] for d in diags))

    def test_internal_constant_patterns_are_reusable(self):
        prog = self.checked("pat-external-values")
        self.assertEqual(prog.diags, [])
        module = prog.modules["pat-external-values"]
        it = Interp(prog)
        pattern = it.get_const(module.consts["pattern"])
        self.assertTrue(it.apply(Named(module.fns["direct"]), [pattern]))
        wrapped = it.get_const(module.consts["wrapped"])
        self.assertEqual(it.apply(Named(module.fns["nested"]), [wrapped]), 1)

    def test_scenario_constants_reject_nested_patterns(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "src").mkdir()
            source = CHECK / "pat-external-values.lm"
            (root / "src" / source.name).write_text(source.read_text())
            scenarios = root / "tests/accept"
            scenarios.mkdir(parents=True)
            (scenarios / "pat.accept").write_text(
                '(scenarios (scenario "Opaque" (status proposed) '
                '(why "Reject opaque external values.") '
                '(run pat-external-values.nested pat-external-values.wrapped) '
                '(expect 1)))')
            result = subprocess.run(
                [sys.executable, "-m", "lm", "check"], cwd=root,
                env={**os.environ, "PYTHONPATH": str(ROOT)},
                capture_output=True, text=True)
            self.assertEqual(result.returncode, 1, result.stderr)
            diags = [json.loads(line) for line in result.stdout.splitlines()]
            self.assertTrue(any(d["code"] == "E-SCENARIO"
                                and "cannot contain Pat" in d["msg"]
                                for d in diags))

