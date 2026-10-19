import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from lm.accept import strip_own_module
from lm.sexpr import read


class TestBacklog12(unittest.TestCase):
    def run_lm(self, *args):
        return subprocess.run(
            [sys.executable, "-m", "lm", *args], capture_output=True, text=True,
        )

    def assert_external_name_error(self, result, qualified="shapes.Circle", *, scenario=False):
        self.assertNotEqual(result.returncode, 0)
        if not scenario:
            self.assertIn("E-NAME-UNRESOLVED", result.stdout + result.stderr)
        self.assertIn(
            f"outside a module write its names qualified: `{qualified}`",
            result.stdout + result.stderr,
        )
        self.assertNotIn("Traceback", result.stderr)

    def test_qualified_run_and_round_trip(self):
        area = self.run_lm("run", "shapes.area", "(shapes.Circle 2)")
        self.assertEqual(area.returncode, 0, area.stderr)
        self.assertEqual(area.stdout.strip(), "12.566370614359172")
        scaled = self.run_lm("run", "shapes.scale", "(shapes.Circle 2)", "3")
        self.assertEqual(scaled.returncode, 0, scaled.stderr)
        self.assertEqual(scaled.stdout.strip(), "(shapes.Circle 6)")
        round_trip = self.run_lm("run", "shapes.area", scaled.stdout.strip())
        self.assertEqual(round_trip.returncode, 0, round_trip.stderr)
        self.assertEqual(round_trip.stdout.strip(), "113.09733552923255")

    def test_unqualified_run_rejected_at_argument_path(self):
        result = self.run_lm("run", "shapes.area", "(Circle 2)")
        self.assert_external_name_error(result)
        diagnostics = [json.loads(line) for line in (result.stdout + result.stderr).splitlines()
                       if line.startswith("{")]
        diagnostic = next(d for d in diagnostics if d["code"] == "E-NAME-UNRESOLVED")
        self.assertEqual(diagnostic["file"], "<arg>")
        self.assertEqual(diagnostic["path"], "arg#0/0")
        self.assertEqual(diagnostic["expected"], "shapes.Circle")
        self.assertEqual(diagnostic["found"], "Circle")
        self.assertEqual(diagnostic["fix"], [
            {"op": "replace-ref", "path": "arg#0/0", "to": "shapes.Circle"},
        ])

    def test_nested_unqualified_names_rejected(self):
        # Even when the outer value has the wrong argument type, every nested
        # module name must be checked before it can reach evaluation.
        for value in ("(list (shapes.Circle 2) (Circle 3))",
                      "(Some (list (Circle 2)))"):
            with self.subTest(value=value):
                self.assert_external_name_error(self.run_lm("run", "shapes.area", value))

    def test_unqualified_type_in_new_rejected(self):
        self.assert_external_name_error(
            self.run_lm("run", "shapes.area", "(new Shape)"), "shapes.Shape",
        )

    def scenario(self, run_value, expectation):
        # Temporary approved input exercises execution without writing a lock.
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "shapes.accept").write_text(
                '(scenarios (scenario "External values" (status approved) '
                '(why "test outside-module constant names") '
                f'(run shapes.scale {run_value} 3) {expectation}))\n'
            )
            return self.run_lm("accept", "--dir", td, "--lock", str(Path(td) / "unused.lock"))

    def test_scenario_qualified_arg_and_expect(self):
        result = self.scenario("(shapes.Circle 2)", "(expect (shapes.Circle 6))")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("PASS  approved", result.stdout)
        self.assertIn("1 pass, 0 FAIL", result.stdout)
        self.assertIn("UNBLESSED", result.stdout)
        self.assertNotIn("Traceback", result.stderr)

    def test_scenario_unqualified_values_fail_without_crashing(self):
        cases = (
            ("(Circle 2)", "(expect (shapes.Circle 6))"),
            ("(shapes.Circle 2)", "(expect (Circle 6))"),
            ("(shapes.Circle 2)", "(expect (list (shapes.Circle 6) (Circle 7)))"),
            ("(shapes.Circle 2)", "(expect-fail DivZero (Some (Circle 2)))"),
        )
        for argument, expectation in cases:
            with self.subTest(argument=argument, expectation=expectation):
                result = self.scenario(argument, expectation)
                self.assert_external_name_error(result, scenario=True)
                self.assertRegex(result.stdout, r"BAD|FAIL")

    def run_project(self, directory, *args):
        wrapper = Path(__file__).resolve().parents[2] / "bin" / "lm"
        return subprocess.run(
            [str(wrapper), *args], cwd=directory, capture_output=True, text=True,
        )

    def write_project(self, directory):
        source = Path(directory) / "src"
        source.mkdir()
        (source / "outsidetest.lm").write_text(
            '(module outsidetest\n'
            '  (purpose "external values test")\n'
            '  (type Shape (sum (Circle (r Int))))\n'
            '  (error Trouble (shape Shape))\n'
            '  (fn echo (purpose "return shapes")\n'
            '    (sig (items (List Shape)) -> (List Shape)) (body items))\n'
            '  (fn reject (purpose "fail with shape")\n'
            '    (sig (s Shape) -> Shape) (fails Trouble) (body (fail Trouble s))))\n'
        )
        formatted = self.run_project(directory, "fmt")
        self.assertEqual(formatted.returncode, 0, formatted.stdout + formatted.stderr)

    def test_nested_qualified_list_in_temporary_project(self):
        with tempfile.TemporaryDirectory() as td:
            self.write_project(td)
            result = self.run_project(
                td, "run", "outsidetest.echo",
                "(list (outsidetest.Circle 2) (outsidetest.Circle 3))",
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(result.stdout.strip(),
                             "(list (outsidetest.Circle 2) (outsidetest.Circle 3))")
            result = self.run_project(
                td, "run", "outsidetest.echo",
                "(list (outsidetest.Circle 2) (Circle 3))",
            )
            self.assert_external_name_error(result, "outsidetest.Circle")

    def test_custom_error_and_nested_fail_arguments(self):
        with tempfile.TemporaryDirectory() as td:
            self.write_project(td)
            scenarios = Path(td) / "scenarios"
            scenarios.mkdir()
            scenario = scenarios / "errors.accept"
            cases = (
                ("outsidetest.Trouble (outsidetest.Circle 2)", None),
                ("Trouble (outsidetest.Circle 2)", "outsidetest.Trouble"),
                ("outsidetest.Trouble (Circle 2)", "outsidetest.Circle"),
            )
            for expected, bad_name in cases:
                with self.subTest(expected=expected):
                    scenario.write_text(
                        '(scenarios (scenario "External error" (status approved) '
                        '(why "test qualified error and its arguments") '
                        '(run outsidetest.reject (outsidetest.Circle 2)) '
                        f'(expect-fail {expected})))\n'
                    )
                    result = self.run_project(
                        td, "accept", "--dir", str(scenarios),
                        "--lock", str(Path(td) / "unused.lock"),
                    )
                    if bad_name:
                        self.assert_external_name_error(result, bad_name, scenario=True)
                        self.assertIn("FAIL  approved", result.stdout)
                    else:
                        self.assertIn("PASS  approved", result.stdout)
                        self.assertIn("1 pass, 0 FAIL", result.stdout)
                        self.assertIn("UNBLESSED", result.stdout)
                    self.assertFalse((Path(td) / "unused.lock").exists())

    def test_source_file_qualified_own_name_keeps_old_diagnostic(self):
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "badown.lm"
            src.write_text(
                '(module badown\n'
                '  (purpose "test")\n'
                '  (type Shape (sum (Circle (r Int))))\n'
                '  (fn test\n'
                '    (purpose "test fn")\n'
                '    (sig -> Shape)\n'
                '    (body (badown.Circle 1))))\n'
            )
            result = self.run_lm("check", str(src))
            self.assertEqual(result.returncode, 1)
            self.assertIn("E-NAME-UNRESOLVED", result.stdout)
            self.assertIn("refer to names of module `badown` unqualified inside it", result.stdout)
            self.assertNotIn("outside a module", result.stdout)

    def test_strings_untouched(self):
        node, _ = read('"shapes.Circle"', "<test>")
        rewritten = strip_own_module(node, "shapes")
        self.assertEqual((rewritten.kind, rewritten.value), ("str", "shapes.Circle"))
        node, _ = read('(list "Circle" "shapes.Circle" shapes.Circle)', "<test>")
        rewritten = strip_own_module(node, "shapes")
        self.assertEqual(rewritten.items[1].value, "Circle")
        self.assertEqual(rewritten.items[2].value, "shapes.Circle")
        self.assertEqual(rewritten.items[3].value, "Circle")
        for value, length in (("Circle", 6), ("shapes.Circle", 13)):
            result = self.run_lm("run", "str.length", f'"{value}"')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), str(length))


if __name__ == "__main__":
    unittest.main()
