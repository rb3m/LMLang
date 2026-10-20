"""Environment/stdin and raw-socket fixtures across all three HTTP adapters."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import select
import socket
import subprocess
import sys
import tempfile
import unittest

from lm.build import find_go, go_build

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / 'tests/spec/http-server'
REASONS = {400: 'Bad Request', 408: 'Request Timeout',
           413: 'Request Entity Too Large', 431: 'Request Header Fields Too Large',
           500: 'Internal Server Error', 501: 'Not Implemented',
           505: 'HTTP Version Not Supported'}


def env():
    result = {k: v for k, v in os.environ.items() if not k.startswith('HTTP_')}
    for k in ('REQUEST_METHOD', 'REQUEST_URI', 'QUERY_STRING',
              'CONTENT_TYPE', 'CONTENT_LENGTH'):
        result.pop(k, None)
    result['PYTHONPATH'] = str(ROOT)
    return result


def error_bytes(code, cgi=False):
    prefix = 'Status: ' if cgi else 'HTTP/1.1 '
    close = '' if cgi else 'Connection: close\r\n'
    return (f'{prefix}{code} {REASONS[code]}\r\nContent-Length: 0\r\n'
            f'{close}\r\n').encode()


def exchange(port, request, expect=False):
    with socket.create_connection(('127.0.0.1', port), timeout=3) as sock:
        if expect:
            head, body = request.split(b'\r\n\r\n', 1)
            sock.sendall(head + b'\r\n\r\n')
            interim = sock.recv(4096)
            if interim != b'HTTP/1.1 100 Continue\r\n\r\n':
                raise AssertionError(interim)
            sock.sendall(body)
        else:
            sock.sendall(request)
        chunks = []
        while True:
            try:
                part = sock.recv(65536)
            except ConnectionResetError:
                break
            if not part:
                break
            chunks.append(part)
        return b''.join(chunks)


@contextmanager
def listener(command, directory):
    p = subprocess.Popen(command, cwd=directory, env=env(),
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        if not select.select([p.stderr], [], [], 5)[0]:
            raise AssertionError('listener did not announce readiness')
        line = p.stderr.readline()
        match = re.fullmatch(rb'listening on http://127\.0\.0\.1:(\d+)\n', line)
        if not match:
            raise AssertionError(line + p.stderr.read() if p.poll() is not None
                                 else line)
        yield int(match[1]), p
    finally:
        p.terminate()
        try:
            p.communicate(timeout=3)
        except subprocess.TimeoutExpired:
            p.kill()
            p.communicate()


class HttpServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.tmp.cleanup)
        cls.directory = Path(cls.tmp.name)
        cls.commands = {'interp': [sys.executable, '-m', 'lm', 'serve',
                                  '--cgi', 'handler.handle',
                                  str(FIXTURES / 'handler.lm')]}
        for target in ('py', 'go'):
            if target == 'go' and find_go() is None:
                sys.stderr.write('\nSKIP: Go missing; server Go suite NOT run\n')
                continue
            output = cls.directory / ('server.py' if target == 'py' else 'server')
            args = [sys.executable, '-m', 'lm', 'build', '--target', target,
                    '--serve', 'handler.handle', str(FIXTURES / 'handler.lm'),
                    '-o', str(output)]
            if target == 'go':
                args += ['--keep-go', str(cls.directory / 'go')]
            p = subprocess.run(args, cwd=cls.directory, env=env(),
                               capture_output=True, timeout=30)
            if p.returncode:
                raise AssertionError(p.stdout + p.stderr)
            cls.commands[target] = ([sys.executable, str(output)]
                                    if target == 'py' else [str(output)])

    def test_cgi_exact_bytes(self):
        cases = json.loads((FIXTURES / 'cgi.json').read_text())
        for case in cases:
            expected = (case['stdout'].encode() if 'stdout' in case else
                        error_bytes(case['status'], cgi=True))
            data = (bytes.fromhex(case['stdin_hex']) if 'stdin_hex' in case else
                    case.get('stdin', '').encode())
            for target, command in self.commands.items():
                with self.subTest(case=case['name'], target=target):
                    p = subprocess.run(command, cwd=self.directory,
                                       env={**env(), **case['env']}, input=data,
                                       capture_output=True, timeout=3)
                    self.assertEqual(p.returncode, 0, p.stderr)
                    self.assertEqual(p.stdout, expected, p.stderr)
                    if 'stdout' in case:
                        self.assertEqual(p.stderr, b'')
                    if 'diagnostic' in case:
                        self.assertEqual(json.loads(p.stderr)['code'],
                                         case['diagnostic'])

    def listen_command(self, target, command):
        if target != 'interp':
            return [*command, '--listen', '--port', '0']
        driver = ('import sys; import lm.http_server as h; '
                  'h.SERVER_HEADER_TIMEOUT = 0.15; '
                  'h.SERVER_TOTAL_TIMEOUT = 0.3; '
                  'from lm.cli import main; sys.exit(main())')
        return [sys.executable, '-c', driver, 'serve', 'handler.handle',
                str(FIXTURES / 'handler.lm'), '--port', '0']

    def test_listener_raw_sockets(self):
        try:
            with socket.socket() as s:
                s.bind(('127.0.0.1', 0))
        except PermissionError as ex:
            self.skipTest(f'sandbox blocks listener socket bind: {ex}')
        # Patches only temporary generated runtime copies, never a shipped knob.
        if 'py' in self.commands:
            path = self.directory / 'server.py'
            text = path.read_text()
            changed = text.replace('SERVER_HEADER_TIMEOUT = 10.0',
                                   'SERVER_HEADER_TIMEOUT = 0.15').replace(
                                       'SERVER_TOTAL_TIMEOUT = 30.0',
                                       'SERVER_TOTAL_TIMEOUT = 0.3')
            self.assertNotEqual(text, changed)
            path.write_text(changed)
        if 'go' in self.commands:
            path = self.directory / 'go/lm_server_listener.go'
            text = path.read_text()
            changed, count = re.subn(
                r'serverHeaderTimeout\s+= 10 \* time.Second',
                'serverHeaderTimeout = 150 * time.Millisecond', text)
            self.assertEqual(count, 1)
            changed, count = re.subn(
                r'serverRequestTimeout\s+= 30 \* time.Second',
                'serverRequestTimeout = 300 * time.Millisecond', changed)
            self.assertEqual(count, 1)
            path.write_text(changed)
            go_build(find_go(), self.directory / 'go', self.directory / 'server')
        bad = [
            (b'GET / HTTP/1.1\r\n' + b'X: a\r\n' * 101 + b'\r\n', 431),
            (b'GET / HTTP/1.1\r\nX: ' + b'a' * 65536 + b'\r\n\r\n', 431),
            (b'POST / HTTP/1.1\r\nContent-Length: 8388609\r\n\r\n', 413),
            (b'POST / HTTP/1.1\r\nTransfer-Encoding: chunked\r\n\r\n', 501),
            (b'POST / HTTP/1.1\r\nTransfer-Encoding: chunked\r\n'
             b'Content-Length: 0\r\n\r\n', 400),
            (b'POST / HTTP/1.1\r\nContent-Length: 0\r\n'
             b'Content-Length: 0\r\n\r\n', 400),
            (b'POST / HTTP/1.1\r\nContent-Length: x\r\n\r\n', 400),
            (b'POST / HTTP/1.1\r\nContent-Length: 0\r\n'
             b'Content-Length: 1\r\n\r\n', 400),
            (b'GET / HTTP/2.0\r\n\r\n', 505),
            (b'CONNECT / HTTP/1.1\r\n\r\n', 501),
            (b'GET / HTTP/1.1\r\n', 408),
            (b'POST / HTTP/1.1\r\nContent-Length: 1\r\n\r\n', 408),
            (b'GET /\xff HTTP/1.1\r\n\r\n', 400),
            (b'GET /?q=\xff HTTP/1.1\r\n\r\n', 400),
            (b'POST / HTTP/1.1\r\nContent-Length: 1\r\n\r\n\xff', 400),
            (b'GET /fault HTTP/1.1\r\n\r\n', 500),
            (b'GET /contract HTTP/1.1\r\n\r\n', 500),
        ]
        results = []
        for target, command in self.commands.items():
            with listener(self.listen_command(target, command),
                          self.directory) as (port, proc):
                observed = []
                for request, code in bad:
                    with self.subTest(target=target, code=code,
                                      request=request[:80]):
                        actual = exchange(port, request)
                        self.assertEqual(actual, error_bytes(code))
                        observed.append(actual)
                requests = [
                    b'GET /?x=%2B HTTP/1.1\r\nX-Z: one\r\n'
                    b'X-A: a\r\nx-z: two\r\n\r\n',
                    b'HEAD / HTTP/1.1\r\n\r\n',
                    b'POST / HTTP/1.0\r\nContent-Length: 3\r\n'
                    b'Expect: 100-continue\r\n\r\nh\xc3\xa9']
                for request in requests:
                    actual = exchange(port, request, b'Expect:' in request)
                    self.assertTrue(actual.startswith(b'HTTP/1.1 200 OK\r\n'))
                    observed.append(actual)
                self.assertIn(b'x-z=one;x-a=a;x-z=two', observed[-3])
                self.assertEqual(observed[-2], b'HTTP/1.1 200 OK\r\n'
                                 b'X-Reply: yes\r\nContent-Length: 9\r\n'
                                 b'Connection: close\r\n\r\n')
                self.assertTrue(observed[-1].endswith('hé'.encode()))
                results.append(observed)
                self.assertIsNone(proc.poll())
                self.assertTrue(select.select([proc.stderr], [], [], 1)[0])
                diagnostics = proc.stderr.read1(65536).splitlines()
                self.assertEqual([json.loads(line)['code']
                                  for line in diagnostics],
                                 ['E-OVERFLOW', 'E-ENSURES-VIOLATED'])
        for result in results[1:]:
            self.assertEqual(result, results[0])

    def test_public_enforced_before_bind(self):
        for target, command in self.commands.items():
            args = ([*command, '--listen'] if target != 'interp' else
                    [*command[:4], *command[5:]])
            p = subprocess.run([*args, '--host', '0.0.0.0'],
                               cwd=self.directory, env=env(), capture_output=True,
                               timeout=3)
            self.assertEqual(p.returncode, 2, (target, p.stdout, p.stderr))
            self.assertEqual(p.stdout, b'')
