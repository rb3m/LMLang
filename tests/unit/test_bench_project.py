import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from lm.bench_project import bench_project

ROOT = Path(__file__).resolve().parents[2]


class TestBenchProject(unittest.TestCase):
    def test_bench_temp_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            (t / "src").mkdir()
            (t / "src" / "sample.lm").write_text("""(module sample
  (use str)
  (export add greet)
  (fn add
    (purpose "Add two integers.")
    (sig (x Int) (y Int) -> Int)
    (example (1 2) => 3)
    (body (+ x y)))
  (fn greet
    (purpose "Greet someone.")
    (sig (name Str) -> Str)
    (example ("world") => "hello world")
    (body (str.concat "hello " name))))
""")
            res = bench_project(t)
            self.assertIsNotNone(res)
            self.assertEqual(res["modules"], 1)
            self.assertEqual(res["functions"], 2)
            self.assertGreater(res["whole_tokens"], 0)
            self.assertGreater(res["s1_median"], 0.0)
            self.assertGreater(res["s2_median"], 0.0)

            # Test CLI with --json
            r = subprocess.run([sys.executable, "-m", "lm", "bench", "--project", str(t), "--json"],
                               cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            data = json.loads(r.stdout)
            self.assertEqual(data["functions"], 2)
            self.assertEqual(data["modules"], 1)

            # Test CLI without --json outputs table and JSON
            r2 = subprocess.run([sys.executable, "-m", "lm", "bench", "--project", str(t)],
                                cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(r2.returncode, 0, r2.stderr)
            self.assertIn("| Metric | Value |", r2.stdout)
            self.assertIn('"functions": 2', r2.stdout)

    def test_bench_ledger_project(self):
        ledger_path = ROOT / "benchprojects" / "ledger"
        res = bench_project(ledger_path)
        self.assertIsNotNone(res)
        self.assertGreaterEqual(res["functions"], 20)
        self.assertEqual(res["modules"], 6)

        # CLI test
        r = subprocess.run([sys.executable, "-m", "lm", "bench", "--project", str(ledger_path), "--json"],
                           cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        data = json.loads(r.stdout)
        self.assertGreaterEqual(data["functions"], 20)
        self.assertEqual(data["modules"], 6)

    def test_bad_path_exits_3(self):
        res = bench_project("/nonexistent/path/that/does/not/exist")
        self.assertIsNone(res)

        r = subprocess.run([sys.executable, "-m", "lm", "bench", "--project", "/nonexistent/path"],
                           cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(r.returncode, 3)


if __name__ == "__main__":
    unittest.main()
