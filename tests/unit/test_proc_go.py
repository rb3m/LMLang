"""Direct Go runtime checks complement shared subprocess differential tests."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from lm.build import find_go, write_sources


class ProcGo(unittest.TestCase):
    def test_direct_process_runtime(self):
        go = find_go()
        if go is None:
            sys.stderr.write(
                '\nSKIP: Go toolchain not found; proc runtime tests NOT run\n')
            self.skipTest('Go toolchain not found')
        fixture = Path(__file__).with_name('proc_fixtures') / 'runtime_test.go'
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            write_sources('package main\nfunc main() {}\n', root)
            (root / 'proc_test.go').write_text(fixture.read_text())
            env = {**os.environ, 'CGO_ENABLED': '0', 'GOTOOLCHAIN': 'local',
                   'GOFLAGS': '-mod=mod'}
            process = subprocess.run([go, 'test', '-v', '.'], cwd=root,
                                     env=env, capture_output=True, timeout=15)
            self.assertEqual(process.returncode, 0,
                             process.stdout + process.stderr)
