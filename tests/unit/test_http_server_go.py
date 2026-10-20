"""Host-free Go server parser and framing tests (net.Pipe, never bind)."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from lm.build import find_go, write_sources


class HttpServerGo(unittest.TestCase):
    def test_server_without_host_sockets(self):
        go = find_go()
        if go is None:
            sys.stderr.write('\nSKIP: Go toolchain absent; server pipe tests\n')
            self.skipTest('Go toolchain not found')
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            write_sources('package main\nfunc main() {}\n', root)
            source = root / 'lm_server_listener.go'
            if source.exists():
                source.write_text(source.read_text().replace(
                    '10 * time.Second', '80 * time.Millisecond').replace(
                    '30 * time.Second', '160 * time.Millisecond'))
            fixture = Path(__file__).with_name('http_fixtures')
            (root / 'server_test.go').write_text(
                (fixture / 'server_test.go').read_text())
            env = {**os.environ, 'CGO_ENABLED': '0', 'GOTOOLCHAIN': 'local',
                   'GOFLAGS': '-mod=mod'}
            result = subprocess.run([go, 'test', '-v', '.'], cwd=root,
                                    env=env, capture_output=True, timeout=90)
            self.assertEqual(result.returncode, 0,
                             result.stdout + result.stderr)
