import unittest
from pathlib import Path

from lm import bench as B


class TestBench(unittest.TestCase):
    def test_every_task_has_lm_python_and_cases(self):
        for d in B.task_dirs():
            self.assertTrue(list(d.glob("*.lm")) and list(d.glob("*.py")) and (d / "cases.json").exists(), d)

    def test_lm_and_python_agree_on_all_cases(self):
        for row in B.equivalence(B.task_dirs()):
            self.assertEqual(row["disagree"], [], row["task"])

    def test_every_mutation_pattern_applies(self):
        by = {d.name: d for d in B.task_dirs()}
        for mod, cat, task, old, new in B.H + B.LOGIC:
            self.assertIsNotNone(B._mutate(by[task], old, new), (mod, cat))

    def test_mutations_are_unique_enough(self):
        ids = [(m, c, o if isinstance(o, str) else o[0]) for m, c, _, o, _ in B.H]
        self.assertEqual(len(ids), len(set(ids)))

    def test_tasks_pass_check_and_test(self):
        import subprocess, sys
        r = subprocess.run([sys.executable, "-m", "lm", "test", *[str(d) for d in B.task_dirs()]], cwd=B.ROOT, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout[-500:])


if __name__ == "__main__":
    unittest.main()
