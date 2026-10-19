"""Host-free checks of interpreter and emitted Python HTTP wire behavior."""
from contextlib import contextmanager
import io
from pathlib import Path
import runpy
import socket
import tempfile
import time
import unittest
from unittest.mock import patch

from lm import http_prims
from lm.check import Checker
from lm.fake_world import FakeWorld
from lm.interp import Interp
from lm.loader import load
from lm.values import Denied
from test_http_client import ROOT, cli, source


class MemorySocket:
    def __init__(self, response):
        self.input = io.BytesIO(response)
        self.sent = b''
        self.timeouts = []
        self.closed = False

    def recv_into(self, buffer):
        data = self.input.read(min(len(buffer), 4096))
        buffer[:len(data)] = data
        return len(data)

    def sendall(self, data):
        self.sent += data

    def settimeout(self, value):
        self.timeouts.append(value)

    def close(self):
        self.closed = True


@contextmanager
def connected(function, sock):
    """Patch source globals or the emitted module's equivalent closure cell."""
    names = function.__code__.co_freevars
    if '_connect' in names:
        cell = function.__closure__[names.index('_connect')]
        original = cell.cell_contents
        cell.cell_contents = lambda *args: sock
        try:
            yield
        finally:
            cell.cell_contents = original
        return
    with patch.dict(function.__globals__, {'_connect': lambda *args: sock}):
        yield


def response(headers=b'', body=b'', status=b'200 OK'):
    return b'HTTP/1.1 ' + status + b'\r\n' + headers + b'\r\n' + body


class HttpWire(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        root = Path(cls.directory.name)
        (root / 'src').mkdir()
        src = root / 'src/http-probe.lm'
        src.write_text(source('http://127.0.0.1:1', 'https://127.0.0.1:1')[0])
        output = root / 'http.py'
        result = cli('build', '--target', 'py', 'http-probe.main', str(src),
                     '-o', str(output), cwd=root)
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)
        cls.emitted = runpy.run_path(str(output), run_name='http_wire_fixture')

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def functions(self):
        return [('interpreter', http_prims.http_request),
                ('python', self.emitted['http_mod'].http_request)]

    def test_response_framing_headers_and_utf8(self):
        cases = [
            (response(b'Content-Length: 3\r\n', 'hé'.encode()), 'GET', 'hé'),
            (response(b'Content-Length: 99\r\n'), 'HEAD', ''),
            (response(status=b'204 No Content'), 'GET', ''),
            (response(b'Content-Length: 0\r\n', status=b'302 Found'),
             'GET', ''),
            (response(b'Transfer-Encoding: chunked\r\n',
                      b'2\r\n\xc3\xa9\r\n1\r\nx\r\n0\r\n\r\n'), 'GET', 'éx'),
            (response(b'Content-Encoding: gzip\r\n'
                      b'Content-Length: 3\r\n', b'raw'),
             'GET', 'raw'),
            (response(b'X: a\r\n' * 100), 'GET', ''),
            (response(b'X: ' + b'a' * 65531 + b'\r\n'), 'GET', ''),
            (response(b'Upgrade: test\r\nConnection: Upgrade\r\n',
                      status=b'101 Switching Protocols'), 'GET', ''),
            (response(b'X: a\r\n' * 50, status=b'103 Early Hints')
             + response(b'X: b\r\n' * 50), 'GET', ''),
            (response(b'Transfer-Encoding: chunked\r\n',
                      b'0\r\n' + b'X: a\r\n' * 99 + b'\r\n'), 'GET', ''),
        ]
        for target, function in self.functions():
            for raw, method, expected in cases:
                with self.subTest(target=target, method=method,
                                  bytes=len(raw)):
                    sock = MemorySocket(raw)
                    with connected(function, sock):
                        result = function(None, method, 'http://localhost/',
                                          (), '')
                    self.assertEqual(dict(result.items)['body'], expected)
                    self.assertNotIn(b'Accept-Encoding:', sock.sent)
                    self.assertTrue(sock.closed)
                    self.assertTrue(all(0 < n <= 30 for n in sock.timeouts))
            sock = MemorySocket(response(b'X-Z: first\r\nX-A: \xff\r\n'
                                         b'x-z: second\r\n'))
            with connected(function, sock):
                result = function(None, 'GET', 'http://localhost/', (), '')
            headers = dict(result.items)['headers']
            self.assertEqual([(p.a, p.b) for p in headers],
                             [('x-a', 'ÿ'), ('x-z', 'first'),
                              ('x-z', 'second')])

    def test_wire_failures_have_only_fixed_categories(self):
        cases = [
            (response(b'Content-Length: 10\r\n', b'x'), 'connect'),
            (response(b'Content-Length: 8388609\r\n'), 'limit'),
            (response(b'X: a\r\n' * 101), 'limit'),
            (response(b'X: ' + b'a' * 65532 + b'\r\n'), 'limit'),
            (response(b'Content-Length: 1\r\n', b'\xff'), 'invalid-utf8'),
            (response(b'Transfer-Encoding: chunked\r\n', b'4\r\nx'),
             'connect'),
            (response(b'X: a\r\n' * 50, status=b'103 Early Hints')
             + response(b'X: b\r\n' * 51), 'limit'),
            (response(b'Transfer-Encoding: chunked\r\n',
                      b'0\r\n' + b'X: a\r\n' * 100 + b'\r\n'), 'limit'),
        ]
        for target, function in self.functions():
            for raw, category in cases:
                with self.subTest(target=target, category=category,
                                  bytes=len(raw)):
                    sock = MemorySocket(raw)
                    with connected(function, sock), \
                            self.assertRaises(Exception) as caught:
                        function(None, 'GET', 'http://localhost/private',
                                 (), '')
                    self.assertEqual(caught.exception.id, 'http.HttpError')
                    self.assertEqual(caught.exception.args_,
                                     ('http://localhost/private', category))
                    self.assertTrue(sock.closed)

    def test_dns_and_connect_deadlines_without_network(self):
        def slow_dns(*args, **kwargs):
            time.sleep(0.08)
            raise socket.gaierror('private details')

        url = 'https://offline.invalid/'
        with patch.object(http_prims, 'HTTP_CONNECT_TIMEOUT', 0.01), \
                patch('socket.getaddrinfo', side_effect=slow_dns):
            with self.assertRaises(Exception) as caught:
                http_prims.http_request(None, 'GET', url, (), '')
        self.assertEqual(caught.exception.args_, (url, 'timeout'))
        with patch('socket.getaddrinfo', side_effect=UnicodeError('private')):
            with self.assertRaises(Exception) as caught:
                http_prims.http_request(None, 'GET', url, (), '')
        self.assertEqual(caught.exception.args_, (url, 'dns'))
        sock = unittest.mock.Mock()
        sock.connect.side_effect = TimeoutError('private address')
        url = 'http://localhost/'
        with patch('socket.socket', return_value=sock):
            with self.assertRaises(Exception) as caught:
                http_prims.http_request(None, 'GET', url, (), '')
        self.assertEqual(caught.exception.args_, (url, 'timeout'))
        self.assertGreater(sock.settimeout.call_args.args[0], 0)
        self.assertLessEqual(sock.settimeout.call_args.args[0], 5)
        sock.close.assert_called_once()

    def test_fake_world_never_calls_http_primitive(self):
        prog = load([str(ROOT / 'stdlib/http.lm')])
        Checker(prog).run()
        interpreter = Interp(prog, allowed={'net.http'}, world=FakeWorld())
        function = prog.modules['http'].fns['request']
        mock = unittest.mock.Mock()
        with patch.dict('lm.fake_world.PRIMS', {'http.request': mock}):
            with self.assertRaises(Denied):
                interpreter.call_fn(function,
                                    ('GET', 'http://localhost/', (), ''))
            mock.assert_not_called()

    def test_network_example_diagnostic_is_explicit(self):
        fixture = ROOT / 'tests/spec/check/mock-http.lm'
        program = load([str(fixture)])
        Checker(program).run()
        errors = [diag for diag in program.diags if diag.severity == 'error']
        self.assertEqual([(diag.code, diag.msg) for diag in errors],
                         [('E-EXAMPLE',
                           'network mocking is not supported yet')])
