"""E-OVERFLOW: 64-bit Int bounds, fault diagnostics (ADR-029, ADR-030)."""
import tempfile
import unittest
from pathlib import Path

from lm.check import Checker
from lm.loader import load
from lm.runner import test_program

ROOT = Path(__file__).resolve().parents[2]

SRC = """(module ov
  (purpose "p")
  (use list)
  (fn deep
    (purpose "p")
    (sig (n Int) -> Int)
    (body (if (= n 0) (list.sum (list 9223372036854775807 1)) (deep (- n 1)))))
  (fn guarded
    (purpose "p")
    (sig (n Int) -> Int)
    (example (9223372036854775807) => 0)
    (body (try (deep 3) (catch DivZero () 0))))
  (fn with-fn
    (purpose "p")
    (sig (f (Fn (Int) Int)) -> Int)
    (body (f 9223372036854775807)))
  (fn uses-fn
    (purpose "p")
    (sig -> Int)
    (example () => 0)
    (body (with-fn (lam ((x Int)) (+ x 1))))))
"""


def diags_for(src):
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "ov.lm"
        p.write_text(src)
        prog = load([str(p)])
        Checker(prog).run()
        assert not [x for x in prog.diags if x.severity == "error"], [x.to_json() for x in prog.diags]
        return test_program(prog)[0]


class Overflow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.d = diags_for(SRC)

    def find(self, op_args):
        return next(x for x in self.d if x.data["operands"] == op_args)

    def test_try_does_not_catch_and_frames_are_capped(self):
        d = self.find([9223372036854775807, 1])
        self.assertEqual(d.code, "E-OVERFLOW")
        self.assertEqual(d.data["frames"], ["`+` (callback)", "list.fold", "ov.deep"])
        # The three self tail calls in ov.deep reuse one frame (ADR-051 item 1).
        self.assertEqual(d.data["frames_omitted"], 2)
        self.assertEqual(d.data["user_path"], "ov/deep/body/1/2")
        self.assertIn("python3 -m lm run ov.deep 0", d.data["replay"])

    def test_function_value_argument_has_no_replay(self):
        d = next(x for x in self.d if x.data["frames"][0].startswith("(lam)"))
        self.assertEqual(d.data["frames"], ["(lam) in ov.uses-fn", "ov.with-fn", "ov.uses-fn"])
        self.assertEqual(d.data["replay"], "unavailable (an argument is a function value)")
        self.assertTrue(d.msg.endswith("add a justified precondition; overflow cannot be caught."))

    def test_long_replay_is_unavailable(self):
        big = "(list" + " 1000000000000000000" * 30 + ")"
        src = SRC.replace("(example () => 0)\n    (body (with-fn", "(body (with-fn")
        src = src.replace("(fn deep", f"(fn many\n    (purpose \"p\")\n    (sig (xs (List Int)) -> Int)\n"
                          f"    (example ({big}) => 0)\n    (body (list.sum xs)))\n  (fn deep")
        d = [x for x in diags_for(src) if x.data["frames"][-1] == "ov.many"][0]
        self.assertEqual(d.data["replay"], "unavailable (arguments exceed 400 characters)")

    def test_literal_counts(self):
        prog = load([str(ROOT / "tests/spec/check/int-literal-range.lm")])
        Checker(prog).run()
        self.assertEqual(sorted(x.found for x in prog.diags if x.code == "E-OVERFLOW"),
                         ["-9223372036854775809", "-99999999999999999999", "9223372036854775808"])


if __name__ == "__main__":
    unittest.main()
