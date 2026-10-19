"""Exercise the full Go HTTP primitive through in-memory connections."""
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

from lm.build import find_go, write_sources


FIXTURES = Path(__file__).with_name('http_fixtures')


class HttpWireGo(unittest.TestCase):
    def test_http_primitive_without_host_sockets(self):
        go = find_go()
        if go is None:
            sys.stderr.write(
                '\nSKIP: Go toolchain not found; HTTP pipe tests NOT run\n')
            self.skipTest('Go toolchain not found')
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            write_sources('package main\nfunc main() {}\n', root)
            path = root / 'lm_prims_http.go'
            original = path.read_text()
            # Only the temporary test copy accepts an in-memory dialer or short
            # deadline. Built binaries expose neither through LM nor their env.
            modified = original.replace(
                '(&net.Dialer{Timeout: httpConnectTimeout})'
                '.DialContext(connectCtx, network, address)',
                'httpTestDial(connectCtx, network, address)')
            modified = re.sub(r'httpTotalTimeout\s+= 30 \* time.Second',
                              'httpTotalTimeout = 300 * time.Millisecond',
                              modified)
            self.assertNotEqual(modified, original)
            path.write_text(modified)
            fixture = (FIXTURES / 'wire_test.go').read_text()
            (root / 'http_test.go').write_text(fixture)
            env = {**os.environ, 'CGO_ENABLED': '0', 'GOTOOLCHAIN': 'local',
                   'GOFLAGS': '-mod=mod',
                   'LM_TEST_CERT': str(FIXTURES / 'cert.pem'),
                   'LM_TEST_KEY': str(FIXTURES / 'key.pem')}
            process = subprocess.run([go, 'test', '-v', '.'], cwd=root,
                                     env=env, capture_output=True, timeout=90)
            self.assertEqual(process.returncode, 0,
                             process.stdout + process.stderr)
