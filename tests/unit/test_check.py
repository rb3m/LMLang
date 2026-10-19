import unittest
from pathlib import Path

from lm.check import Checker
from lm.loader import load

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "tests/spec/check"


def run(path):
    prog = load([str(path)])
    Checker(prog).run()
    return prog


def codes(prog, keep_noncanonical):
    return sorted({d.code for d in prog.diags if keep_noncanonical or d.code != "E-NONCANONICAL"})


class SpecFixtures(unittest.TestCase):
    def test_single_file_cases(self):
        for f in sorted(CHECK.glob("*.lm")):
            want = sorted(f.with_suffix(".expect").read_text().split())
            got = codes(run(f), "E-NONCANONICAL" in want)
            self.assertEqual(got, want, f.name)

    def test_directory_cases(self):
        for d in sorted(p for p in CHECK.iterdir() if p.is_dir()):
            want = sorted((d / "expect").read_text().split())
            self.assertEqual(codes(run(d), False), want, d.name)

    def test_every_check_code_has_a_fixture(self):
        covered = set()
        for e in list(CHECK.glob("*.expect")) + list(CHECK.glob("*/expect")) + list((ROOT / "tests/spec/run").glob("*.expect")):
            covered |= set(e.read_text().split())
        # E-EFFECT-DENIED needs CLI flags; E-PROOF-VIOLATED needs --no-contracts (ADR-061)
        later = {"E-EFFECT-DENIED", "E-PROOF-VIOLATED"}
        from lm.diag import CODES
        # Acceptance files have fixtures in test_accept_validation.py.
        separate = {"E-NONCANONICAL", "E-SCENARIO"}
        self.assertEqual(sorted(set(CODES) - covered - later - separate), [])


class StdlibAndDiagnostics(unittest.TestCase):
    def test_stdlib_is_clean(self):
        prog = run(ROOT / "stdlib")
        self.assertEqual([d.to_json() for d in prog.diags], [])

    def test_diagnostic_has_fix_and_path(self):
        prog = run(CHECK / "unresolved-qualified.lm")
        d = [d for d in prog.diags if d.code == "E-NAME-UNRESOLVED"][0]
        self.assertEqual(d.path, "unresolved-qualified/f/body/1/0")
        self.assertEqual(d.fix, [{"op": "replace-ref", "path": d.path, "to": "list.sum"}])
        self.assertIn("list.sum", d.expected)

    def test_use_missing_fix(self):
        d = run(CHECK / "use-missing.lm").diags[0]
        self.assertEqual(d.fix, [{"op": "add-use", "module": "use-missing", "use": "list"}])

    def test_call_graph_recorded(self):
        prog = run(CHECK / "ok-basic.lm")
        self.assertIn("list.sum", prog.calls["ok-basic.total"])
        self.assertIn("math.min", prog.calls["ok-basic.clamp"])

    def test_fix_for_undeclared_effect(self):
        d = [d for d in run(CHECK / "effect-undeclared.lm").diags if d.code == "E-EFFECT-UNDECLARED"][0]
        self.assertEqual(d.fix, [{"op": "add-eff", "fn": "effect-undeclared.f", "eff": "io.out"}])

    def test_pair_map_key_diagnostic_suggests_alternatives(self):
        prog = run(CHECK / "map-key-pair.lm")
        type_diags = [d for d in prog.diags if d.code == "E-TYPE"]
        self.assertTrue(type_diags)
        for d in type_diags:
            self.assertIn("Str key", d.msg)
            self.assertIn("nested maps", d.msg)

    def test_pair_shadowing_diagnostic_suggests_p(self):
        prog_param = run(CHECK / "dup-pair-param.lm")
        d_param = prog_param.diags[0]
        self.assertEqual(d_param.code, "E-DUP-NAME")
        self.assertIn("name it `p` instead", d_param.msg)
        prog_local = run(CHECK / "dup-pair-local.lm")
        d_local = prog_local.diags[0]
        self.assertEqual(d_local.code, "E-DUP-NAME")
        self.assertIn("name it `p` instead", d_local.msg)

    def test_for_early_exit_diagnostics(self):
        for name in ("for-break", "for-continue", "for-return"):
            d = run(CHECK / f"{name}.lm").diags[0]
            self.assertEqual(d.code, "E-NAME-UNRESOLVED")
            self.assertIn("LM has no early exit (use a recursive function or `list.fold`)", d.msg)

    def test_lambda_mixed_params_diagnostic(self):
        d = run(CHECK / "lambda-mixed-params.lm").diags[0]
        self.assertEqual(d.code, "E-PARSE")
        self.assertIn("cannot mix typed and untyped parameters", d.msg)

    def test_lambda_unresolved_names_parameter(self):
        d = run(CHECK / "lambda-unresolved.lm").diags[0]
        self.assertEqual(d.code, "E-TYPE")
        self.assertIn("cannot infer type for lambda parameter `x`", d.msg)


if __name__ == "__main__":
    unittest.main()


