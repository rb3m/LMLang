"""Scoped standard library discovery."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from lm.printer import format_text


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
        extensions = sorted(p.stem for p in (ROOT / 'ext').glob('*.lm'))
        modules.extend(extensions)
        self.assertEqual([s.split()[0] for s in lines], modules)
        for line in lines:
            self.assertRegex(line, r'^\S+  \d+ exports  .+')
        for stem, line in zip(extensions, lines[-len(extensions):]):
            self.assertTrue(line.endswith(f'opt-in: (ext {stem}) in lm.deps'))
        self.assertNotIn('notes:', result.stdout)

    def test_module(self):
        result = run_lm(['index', '--module', 'str'])
        self.assertEqual(result.returncode, 0, result.stderr)
        full = run_lm(['index', '--stdlib']).stdout.splitlines()
        start = next(i for i, s in enumerate(full)
                     if s.startswith('module str '))
        end = next((i for i in range(start + 1, len(full))
                    if full[i].startswith('module ')), len(full))
        header, notes, *symbols = result.stdout.splitlines()
        self.assertTrue(notes.startswith('  notes: '))
        self.assertEqual([header, *symbols], full[start:end])
        explicit = run_lm(['index', '--stdlib', '--module', 'str'])
        self.assertEqual(result.stdout, explicit.stdout)

    def test_library_modules_carry_notes(self):
        required = (
            'bytes', 'date', 'env', 'float', 'fs', 'hid', 'http', 'io', 'json',
            'list', 'map', 'math', 'opt', 'pair', 'pat', 'proc', 'rand', 'set',
            'str', 'time', 'vec',
        )
        with tempfile.TemporaryDirectory() as project:
            for stem in required:
                with self.subTest(stem=stem):
                    result = run_lm(['index', '--module', stem], cwd=project)
                    self.assertEqual((result.returncode, result.stderr), (0, ''))
                    self.assertRegex(result.stdout.splitlines()[1], r'^  notes: \S')

    def test_notes_at_byte_limit_format_on_one_line(self):
        notes = 'é' * 250
        source = f'(module fixture (notes "{notes}") (purpose "Test notes."))'
        canonical, diags = format_text(source)
        self.assertFalse(diags)
        self.assertEqual(canonical, f'(module fixture\n  (purpose "Test notes.")\n  (notes "{notes}"))\n')

    def test_errors(self):
        for args in (['--modules'],
                     ['--stdlib', '--modules', '--module', 'str'],
                     ['--stdlib', '--modules', 'src'],
                     ['--stdlib', '--module', 'str', 'src']):
            with self.subTest(args=args):
                self.assertEqual(run_lm(['index', *args]).returncode, 3)
        result = run_lm(['index', '--stdlib', '--module', 'missing'])
        self.assertEqual(result.returncode, 3)
        self.assertIn('available modules:', result.stderr)
        self.assertIn('str', result.stderr)
