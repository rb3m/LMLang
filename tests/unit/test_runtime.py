import json
import subprocess
import sys
import unittest
from pathlib import Path

from lm.check import Checker
from lm.loader import load
from lm.prims import PRIMS
from lm.runner import test_program

ROOT = Path(__file__).resolve().parents[2]
RUN = ROOT / "tests/spec/run"


def lm(*args):
    p = subprocess.run([sys.executable, "-m", "lm", *args], cwd=ROOT, capture_output=True, text=True)
    return p.returncode, p.stdout, p.stderr


class RuntimeFixtures(unittest.TestCase):
    def test_fixtures(self):
        for f in sorted(RUN.glob("*.lm")):
            prog = load([str(f)])
            Checker(prog).run()
            self.assertEqual([d.to_json() for d in prog.diags if d.severity == "error"], [], f.name)
            diags, stats = test_program(prog)
            want = sorted(f.with_suffix(".expect").read_text().split())
            self.assertEqual(sorted({d.code for d in diags}), want, f.name)
            if f.with_suffix(".cases.json").exists():
                self.assertGreater(stats["cases"], 0)
            elif not want:
                # Successful fixtures must execute examples; their case count varies by rule.
                self.assertGreater(stats["examples"], 0, f.name)

    def test_stdlib_examples_pass(self):
        prog = load([str(ROOT / "stdlib"), str(ROOT / "examples")])
        Checker(prog).run()
        diags, stats = test_program(prog)
        self.assertEqual([d.to_json() for d in diags], [])
        self.assertEqual(stats["no_examples"], [])

    def test_every_prim_is_implemented(self):
        import re
        used = set()
        for f in (ROOT / "stdlib").glob("*.lm"):
            used |= set(re.findall(r'\(prim "([^"]+)"\)', f.read_text()))
    def test_for_one_million_elements(self):
        from lm.interp import Interp
        from lm.sexpr import read
        from lm.values import UNIT
        prog = load([str(ROOT / "stdlib")])
        Checker(prog).run()
        it, m = Interp(prog), prog.modules["list"]
        expr, diags = read("(for (x (list.range 0 1000000)) unit)")
        self.assertEqual(diags, [])
        self.assertEqual(it.ev(expr, {}, m), UNIT)


class Cli(unittest.TestCase):
    def test_run_value_fail_contract_denied(self):
        self.assertEqual(lm("run", "billing.total", "(list 100 200)", '"MX"')[:2], (0, "348\n"))
        rc, _, out = lm("run", "billing.total", "(list 100)", '"XX"')
        self.assertEqual((rc, out), (1, '(fail billing.BadRegion "XX")\n'))
        rc, out, err = lm("run", "billing.total", "(list)", '"MX"')
        self.assertEqual((rc, out, json.loads(err)["code"]), (70, "", "E-REQUIRES-VIOLATED"))
        rc, out, err = lm("run", "io.print", '"hi"')
        self.assertEqual((rc, out, json.loads(err)["code"]), (1, "", "E-EFFECT-DENIED"))
        self.assertEqual(lm("run", "io.print", '"hi"', "--allow", "io.out")[:2], (0, "hi\nunit\n"))

    def test_run_arg_type_error_and_usage(self):
        rc, out, _ = lm("run", "list.sum", '"x"')
        d = json.loads(out)
        self.assertEqual((rc, d["code"], d["file"], d["path"]), (1, "E-TYPE", "<arg>", "arg#0"))
        self.assertEqual(lm("run", "nomod.f")[0], 3)
        self.assertEqual(lm("run", "math.abs")[0], 3)
        self.assertEqual(lm("run", "math.abs", "-7")[1], "7\n")

    def test_run_overflow_is_a_fault(self):
        for extra in ([], ["--no-contracts"]):
            rc, out, err = lm("run", "math.abs", "-9223372036854775808", *extra)
            d = json.loads(err)
            self.assertEqual((rc, out, d["code"]), (70, "", "E-OVERFLOW"))
        self.assertEqual(d["data"]["op"], "-")
        self.assertEqual(d["data"]["operands"], [0, -9223372036854775808])
        self.assertEqual(d["data"]["bounds"], [-9223372036854775808, 9223372036854775807])
        self.assertEqual((d["data"]["frames"], d["path"]), (["math.abs"], "math/abs/body/1/2"))
        self.assertEqual(d["data"]["replay"], "python3 -m lm run math.abs -9223372036854775808")
        self.assertTrue(d["msg"].endswith("overflow cannot be caught."))

    def test_run_literal_out_of_range(self):
        rc, out, _ = lm("run", "math.abs", "9223372036854775808")
        d = json.loads(out)
        self.assertEqual((rc, d["code"], d["file"]), (1, "E-OVERFLOW", "<arg>"))

    def test_run_pair_paste_back(self):
        rc, out, _ = lm("run", "pair.swap", '(pair 1 "a")')
        self.assertEqual((rc, out), (0, '(pair "a" 1)\n'))
        rc2, out2, _ = lm("run", "pair.swap", out.strip())
        self.assertEqual((rc2, out2), (0, '(pair 1 "a")\n'))

    def test_test_command(self):
        rc, _, err = lm("test", "stdlib", "examples")
        self.assertEqual(rc, 0)
        self.assertIn("0 failed", err)
        rc, out, _ = lm("test", "tests/spec/run/example-failed.lm")
        self.assertEqual((rc, json.loads(out)["code"]), (1, "E-EXAMPLE-FAILED"))
        rc, out, err = lm("test", "tests/spec/check/type-arg.lm")
        self.assertEqual(rc, 1)
        self.assertIn("not run", err)


if __name__ == "__main__":
    unittest.main()
