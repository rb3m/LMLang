"""Real OS boundary tests for the function runner."""
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


def run(fn, *args, data=b''):
    return subprocess.run([sys.executable, '-m', 'lm', 'run', fn, *args],
                          cwd=ROOT, input=data, capture_output=True)


class RealIO(unittest.TestCase):
    def test_args(self):
        p = run('io.args', '--allow', 'io.in', '--', 'A', '--allow', 'é')
        self.assertEqual((p.returncode, p.stdout), (0, '(list "A" "--allow" "é")\n'.encode()))
        self.assertEqual(run('io.args', '--allow', 'io.in').stdout, b'(list)\n')

    def test_stdin(self):
        for data, expected in [(b'', b'None\n'), (b'\n', b'(Some "")\n'),
                               (b'a\r\nb', b'(Some "a")\n'), (b'last', b'(Some "last")\n')]:
            p = run('io.read-line', '--allow', 'io.in', data=data)
            self.assertEqual((p.returncode, p.stdout), (0, expected))
        self.assertEqual(run('io.read-all', '--allow', 'io.in', data=b'a\r\nb').stdout,
                         b'"a\\u{d}\\nb"\n')
        for fn in ['io.read-line', 'io.read-all']:
            p = run(fn, '--allow', 'io.in', data=b'\xff')
            self.assertEqual(p.returncode, 1)
            self.assertTrue(p.stderr.startswith(b'(fail io.IoError '), p.stderr)

    def test_utf8_output_despite_host_encoding(self):
        env = dict(os.environ, PYTHONIOENCODING="ascii")
        p = subprocess.run([sys.executable, "-m", "lm", "run", "io.eprint", '"é"', "--allow", "io.out"], cwd=ROOT, env=env, capture_output=True)
        self.assertEqual((p.returncode, p.stderr), (0, "é\n".encode()))

    def test_output(self):
        p = run('io.eprint', '"hi"', '--allow', 'io.out')
        self.assertEqual((p.returncode, p.stdout, p.stderr), (0, b'unit\n', b'hi\n'))

    def test_files(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'text'
            arg = json.dumps(str(path))
            self.assertEqual(run('fs.exists', arg, '--allow', 'fs.read').stdout, b'false\n')
            p = run('fs.write', arg, '"é\\n"', '--allow', 'fs.write')
            self.assertEqual((p.returncode, p.stdout), (0, b'unit\n'))
            self.assertEqual(path.read_bytes(), 'é\n'.encode())
            self.assertEqual(run('fs.read', arg, '--allow', 'fs.read').stdout, '"é\\n"\n'.encode())
            self.assertEqual(run('fs.exists', arg, '--allow', 'fs.read').stdout, b'true\n')
            path.write_bytes(b'\xff')
            p = run('fs.read', arg, '--allow', 'fs.read')
            self.assertEqual(p.returncode, 1)
            self.assertTrue(p.stderr.startswith(b'(fail fs.IoError '))
            for fn in ['fs.read', 'fs.write', 'fs.exists']:
                args = [json.dumps(str(path / 'child'))]
                if fn == 'fs.write': args.append('"x"')
                p = run(fn, *args, '--allow', 'fs.write' if fn == 'fs.write' else 'fs.read')
                self.assertEqual(p.returncode, 1, (fn, p.stderr))
                self.assertTrue(p.stderr.startswith(b'(fail fs.IoError '), (fn, p.stderr))

    def test_denied_effects(self):
        for fn in ['io.args', 'io.read-line', 'io.read-all', 'io.eprint', 'fs.read', 'fs.write', 'fs.exists']:
            args = ['"x"'] if fn in ['io.eprint', 'fs.read', 'fs.exists'] else ['"x"', '"y"'] if fn == 'fs.write' else []
            p = run(fn, *args)
            self.assertEqual(p.returncode, 1)  # missing --allow is not a fault (ADR-034 merge note)
            self.assertEqual(json.loads(p.stderr)['code'], 'E-EFFECT-DENIED')
            self.assertEqual(p.stdout, b'')

    def test_huge_parse_is_none(self):
        p = run('str.to-int', json.dumps('9' * 5000))
        self.assertEqual((p.returncode, p.stdout), (0, b'None\n'))


class ScriptFixtures(unittest.TestCase):
    def test_stream_sequence_and_catch(self):
        from lm.check import Checker
        from lm.interp import Interp
        from lm.loader import load
        prog = load([str(ROOT / 'tests/spec/run/strings.lm')])
        Checker(prog).run()
        self.assertFalse([d for d in prog.diags if d.severity == 'error'])
        it = Interp(prog, allowed=['io.in', 'fs.read'], stdin=io.BytesIO(b'a\r\nb\nrest'))
        self.assertEqual(it.call_fn(prog.modules['strings'].fns['read-pair'], []), 'abrest')
        with tempfile.TemporaryDirectory() as d:
            path = str(Path(d) / 'missing')
            self.assertEqual(it.call_fn(prog.modules['strings'].fns['catch-read'], [path]), path)

    def test_cr_lines(self):
        from lm.str_prims import lines
        self.assertEqual(lines(None, 'a\r\nb\rc\n'), ('a', 'b', 'c'))
        self.assertEqual(lines(None, '\r\n'), ('',))
        self.assertEqual(lines(None, 'a\v b'), ('a\v b',))
