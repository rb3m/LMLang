"""Real POSIX subprocess behavior shared by interpreter, Python and Go."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import unittest

from lm.build import find_go, go_build
from proc_support import source


ROOT = Path(__file__).resolve().parents[2]


def cli(*args, cwd=ROOT):
    return subprocess.run([sys.executable, '-m', 'lm', *args], cwd=cwd,
                          env={**os.environ, 'PYTHONPATH': str(ROOT)},
                          capture_output=True, timeout=90)


@unittest.skipUnless(os.name == 'posix', 'POSIX subprocess runtime')
class ProcTests(unittest.TestCase):
    def test_effect_gate(self):
        result = cli('run', 'proc.run', '(list "/bin/sh")', '""',
                     'None', '(list)')
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(json.loads(result.stderr)['code'], 'E-EFFECT-DENIED')

    def test_fixed_limits_and_platform_guard(self):
        from unittest.mock import patch
        from lm import proc_prims
        from lm.values import LmFail, Var
        self.assertEqual(proc_prims.PROC_TOTAL_TIMEOUT, 30.0)
        self.assertEqual(proc_prims.PROC_OUTPUT_LIMIT, 8 * 1024 * 1024)
        with patch.object(proc_prims.os, 'name', 'nt'):
            with self.assertRaises(LmFail) as caught:
                proc_prims.proc_run(None, ('/bin/sh',), '',
                                    Var('', 'None'), ())
        self.assertEqual(caught.exception.args_, ('unsupported',))

    def differential(self, target):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / 'src').mkdir()
            (root / 'noexec').write_text('private content')
            executable = root / 'text-executable'
            executable.write_text('echo SHOULD_NOT_EXECUTE\n')
            executable.chmod(0o755)
            text, expected = source(root)
            early_stdin = []
            early_expected = b''
            for script, code, stdout in (('head -c 5', 0, 'xxxxx'),
                                         ('exit 3', 3, '')):
                label = f'early stdin: {script}'
                early_stdin.append(
                    '(io.print (if (= '
                    f'(proc.run (list "/bin/sh" "-c" {json.dumps(script)}) '
                    '(str.repeat "x" 2000000) None (list)) '
                    f'(new proc.Result (exit (proc.Exited {code})) '
                    f'(stdout {json.dumps(stdout)}) (stderr ""))) '
                    f'{json.dumps(label)} "BAD early stdin"))')
                early_expected += label.encode() + b'\n'
            marker = '(body (do '
            self.assertEqual(text.count(marker), 1)
            text = text.replace(marker, marker + ' '.join(early_stdin) + ' ', 1)
            expected = early_expected + expected
            path = root / 'src/proc-probe.lm'
            path.write_text(text)
            operation = json.dumps({'op': 'fmt', 'file': str(path)})
            result = cli('edit', 'apply', operation, cwd=root)
            self.assertEqual(result.returncode, 0,
                             result.stdout + result.stderr)
            if target == 'interp':
                driver = ('import sys; import lm.proc_prims as p; '
                          'p.PROC_TOTAL_TIMEOUT = 0.5; '
                          'from lm.cli import main; sys.exit(main())')
                command = [sys.executable, '-c', driver, 'run',
                           'proc-probe.main', '--allow', 'proc.run',
                           '--allow', 'io.out']
                expected += b'0\n'
            else:
                output = root / ('probe.py' if target == 'py' else 'probe')
                args = ['build', '--target', target, 'proc-probe.main',
                        str(path), '-o', str(output)]
                if target == 'go':
                    args += ['--keep-go', str(root / 'go')]
                result = cli(*args, cwd=root)
                self.assertEqual(result.returncode, 0,
                                 result.stdout + result.stderr)
                if target == 'py':
                    original = output.read_text()
                    modified = original.replace('PROC_TOTAL_TIMEOUT = 30.0',
                                                'PROC_TOTAL_TIMEOUT = 0.5')
                    self.assertNotEqual(original, modified)
                    output.write_text(modified)
                    command = [sys.executable, str(output)]
                else:
                    path = root / 'go/lm_prims_proc.go'
                    original = path.read_text()
                    modified = re.sub(r'procTotalTimeout\s+='
                                      r' 30 \* time.Second',
                                      'procTotalTimeout = '
                                      '500 * time.Millisecond',
                                      original)
                    self.assertNotEqual(original, modified)
                    path.write_text(modified)
                    go_build(find_go(), root / 'go', output)
                    command = [str(output)]
            env = {**os.environ, 'PYTHONPATH': str(ROOT), 'SECRET': 'hidden'}
            result = subprocess.run(
                command, cwd=root, env=env,
                capture_output=True, timeout=15)
            self.assertEqual(result.returncode, 0,
                             result.stdout + result.stderr)
            self.assertEqual(result.stdout, expected, result.stderr)
            for name in ('grandchild.pid', 'pipe-grandchild.pid'):
                pid = int((root / name).read_text())
                deadline = time.monotonic() + 1
                while time.monotonic() < deadline:
                    probe = subprocess.run(['/bin/kill', '-0', str(pid)],
                                           capture_output=True)
                    if probe.returncode:
                        break
                    time.sleep(0.02)
                self.assertNotEqual(probe.returncode, 0,
                                    f'grandchild {pid} survived timeout')

    def test_interpreter(self):
        self.differential('interp')

    def test_python(self):
        self.differential('py')

    def test_go(self):
        if find_go() is None:
            sys.stderr.write(
                '\nSKIP: Go absent; subprocess differential NOT run\n')
            self.skipTest('Go toolchain not found')
        self.differential('go')
