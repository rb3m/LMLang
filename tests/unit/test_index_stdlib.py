"""Scoped standard library discovery."""
import os
from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[2]


def run_lm(args, cwd=ROOT):
    env = dict(os.environ, PYTHONPATH=str(ROOT))
    return subprocess.run([sys.executable, '-m', 'lm', *args], cwd=cwd,
                          env=env, text=True, capture_output=True)


class StdlibIndexTests(unittest.TestCase):
    def test_modules(self):
        result = run_lm(['index', '--stdlib', '--modules'])
        self.assertEqual(result.returncode, 0, result.stderr)
        lines = result.stdout.splitlines()
        self.assertTrue(lines)
        modules = sorted(p.stem for p in (ROOT / 'stdlib').glob('*.lm'))
        self.assertEqual([s.split()[0] for s in lines], modules)
        for line in lines:
            self.assertRegex(line, r'^\S+  \d+ exports  .+')

    def test_module(self):
        result = run_lm(['index', '--stdlib', '--module', 'str'])
        self.assertEqual(result.returncode, 0, result.stderr)
        full = run_lm(['index', '--stdlib']).stdout.splitlines()
        start = next(i for i, s in enumerate(full)
                     if s.startswith('module str '))
        end = next((i for i in range(start + 1, len(full))
                    if full[i].startswith('module ')), len(full))
        self.assertEqual(result.stdout.splitlines(), full[start:end])

    def test_errors(self):
        for args in (['--modules'], ['--module', 'str'],
                     ['--stdlib', '--modules', '--module', 'str'],
                     ['--stdlib', '--modules', 'src'],
                     ['--stdlib', '--module', 'str', 'src']):
            with self.subTest(args=args):
                self.assertEqual(run_lm(['index', *args]).returncode, 3)
        result = run_lm(['index', '--stdlib', '--module', 'missing'])
        self.assertEqual(result.returncode, 3)
        self.assertIn('stdlib modules:', result.stderr)
        self.assertIn('str', result.stderr)
