import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def lm(*args):
    p = subprocess.run([sys.executable, "-m", "lm", *args], cwd=ROOT, capture_output=True, text=True)
    return p.returncode, p.stdout, p.stderr


class CliTests(unittest.TestCase):
    def test_fmt_rewrites_then_check_passes(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "m.lm"
            f.write_text("(module m (fn b (body 1)) (fn a (body 2)))")
            rc, out, _ = lm("fmt", "--check", str(f))
            self.assertEqual(rc, 1)
            diag = json.loads(out.splitlines()[0])
            self.assertEqual((diag["code"], diag["severity"], diag["path"]), ("E-NONCANONICAL", "warning", "m"))
            self.assertEqual(f.read_text(), "(module m (fn b (body 1)) (fn a (body 2)))")  # --check never writes
            self.assertEqual(lm("fmt", str(f))[0], 0)
            self.assertEqual(lm("fmt", "--check", str(f))[0], 0)
            self.assertTrue(f.read_text().startswith("(module m\n  (fn a"))

    def test_error_is_json_line_and_file_untouched(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "m.lm"
            f.write_text("(module m")
            rc, out, _ = lm("fmt", str(f))
            self.assertEqual(rc, 1)
            self.assertEqual(json.loads(out)["code"], "E-PARSE")
            self.assertEqual(f.read_text(), "(module m")

    def test_usage_errors(self):
        self.assertEqual(lm()[0], 3)
        self.assertEqual(lm("fmt", "nope.lm")[0], 3)
        self.assertEqual(lm("fmt", "--bogus")[0], 3)
        self.assertEqual(lm("run")[0], 3)

    def test_run_const_arguments(self):
        import os
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "src"
            src.mkdir()
            (src / "app.lm").write_text(
                '(module app\n'
                '  (purpose "App.")\n'
                '  (export id moon-gravity)\n'
                '  (const moon-gravity\n'
                '    (purpose "Gravity.")\n'
                '    (type Float)\n'
                '    (value 1.62))\n'
                '  (fn id\n'
                '    (purpose "Identity.")\n'
                '    (sig (x Float) -> Float)\n'
                '    (example (1.0) => 1.0)\n'
                '    (body x)))\n'
            )
            env = {**os.environ, "PYTHONPATH": str(ROOT)}
            # Qualified const succeeds
            p = subprocess.run([sys.executable, "-m", "lm", "run", "app.id", "app.moon-gravity"],
                               cwd=d, env=env, capture_output=True, text=True)
            self.assertEqual(p.returncode, 0)
            self.assertIn("1.62", p.stdout.splitlines())

            # Unqualified const triggers E-NAME-UNRESOLVED with qualified suggestion
            p = subprocess.run([sys.executable, "-m", "lm", "run", "app.id", "moon-gravity"],
                               cwd=d, env=env, capture_output=True, text=True)
            self.assertEqual(p.returncode, 1)
            self.assertEqual(p.stdout, "")
            errs = [json.loads(line) for line in p.stderr.splitlines()
                    if line.startswith("{")]
            unresolved = [d for d in errs if d["code"] == "E-NAME-UNRESOLVED"]
            self.assertTrue(unresolved)
            self.assertEqual(unresolved[0]["expected"], "app.moon-gravity")


if __name__ == "__main__":
    unittest.main()
