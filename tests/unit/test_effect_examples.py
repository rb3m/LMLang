"""Fake-world examples execute hermetically and survive tooling round trips."""
import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path

from lm.check import Checker
from lm.explain import explain
from lm.index import Index
from lm.loader import load
from lm.lower import lower_examples
from lm.printer import flat, format_text
from lm.runner import example_outcomes, test_program

ROOT = Path(__file__).resolve().parents[2]
RUN = ROOT / "tests/spec/run"


def checked(path):
    prog = load([str(path)])
    Checker(prog).run()
    errors = [d.to_json() for d in prog.diags if d.severity == "error"]
    if errors:
        raise AssertionError(errors)
    return prog


class EffectExamples(unittest.TestCase):
    def test_runner_is_hermetic_and_counts_examples(self):
        prog = checked(RUN / "effect-examples.lm")
        out, err = io.StringIO(), io.StringIO()
        host_env = dict(os.environ)
        with tempfile.TemporaryDirectory() as tmp:
            old_cwd = Path.cwd()
            try:
                os.chdir(tmp)
                Path("x.txt").write_text("host file", encoding="utf-8")
                with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                    diags, stats = test_program(prog)
                self.assertEqual(Path("x.txt").read_text(encoding="utf-8"), "host file")
                Path("x.txt").unlink()
                with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                    again, _ = test_program(prog)
                self.assertFalse(Path("x.txt").exists())
            finally:
                os.chdir(old_cwd)
        self.assertEqual([d.to_json() for d in diags + again], [])
        self.assertEqual(stats["failed"], 0)
        self.assertEqual(stats["examples"], 12)
        self.assertEqual((out.getvalue(), err.getvalue()), ("", ""))
        self.assertEqual(dict(os.environ), host_env)

    def test_mismatches_include_checks_after_expected_failure(self):
        diags, stats = test_program(checked(RUN / "effect-mismatch.lm"))
        self.assertEqual(stats["failed"], 5)
        self.assertEqual({d.code for d in diags}, {"E-EXAMPLE-FAILED"})
        failed = next(d for d in diags if "/fail-check-mismatch/" in d.path)
        self.assertIn('(file "x.txt" "wrong")', failed.expected)
        self.assertIn('(file "x.txt" "saved")', failed.found)

    def test_compiled_enumeration_skips_fake_examples(self):
        prog = checked(RUN / "effect-examples.lm")
        _, cases = lower_examples(prog, prog.targets)
        self.assertEqual(cases, [])
        self.assertEqual(example_outcomes(prog, prog.targets), {})

    def test_tree_checks_defaults_and_nested_world(self):
        diags, stats = test_program(checked(RUN / "effect-world-details.lm"))
        self.assertEqual([d.to_json() for d in diags], [])
        self.assertEqual(stats["examples"], 17)
        self.assertEqual(stats["no_examples"], [])
        diags, stats = test_program(checked(RUN / "effect-check-mismatch.lm"))
        self.assertEqual(stats["failed"], 4)
        self.assertEqual({d.code for d in diags}, {"E-EXAMPLE-FAILED"})

    def test_faults_keep_contracts_enabled_and_output_captured(self):
        prog = checked(RUN / "effect-faults.lm")
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            diags, stats = test_program(prog)
        self.assertEqual(stats["failed"], 3)
        self.assertEqual({d.code for d in diags}, {
            "E-REQUIRES-VIOLATED", "E-ENSURES-VIOLATED", "E-OVERFLOW"})
        self.assertEqual((out.getvalue(), err.getvalue()), ("", ""))

    def test_fmt_slice_explain_round_trip(self):
        source = (RUN / "effect-examples.lm").read_text(encoding="utf-8")
        text, diags = format_text(source)
        self.assertEqual(diags, [])
        self.assertEqual(format_text(text), (text, []))
        prog = checked(RUN / "effect-examples.lm")
        idx = Index(prog)
        fn = prog.modules["effect-examples"].fns["echo"]
        example = flat(fn.clauses["example"][0])
        self.assertIn(example, text)
        sliced, _, _ = idx.slice(fn.qual)
        self.assertIn(example, sliced)
        description = explain(prog, idx, fn)
        self.assertIn('(given (stdin "hello")) => unit', description)
        self.assertIn('(out "hello\\n") (err "hello\\n")', description)


if __name__ == "__main__":
    unittest.main()
