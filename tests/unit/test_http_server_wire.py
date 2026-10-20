"""Host-free HTTP server framing and rejection contracts (ADR-076)."""
import io
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from lm import cli_serve, http_server
from lm.pybackend_embed import wrap_module
from lm.serve_options import parse_serve_args


class MemorySocket:
    def __init__(self, request):
        self.input = io.BytesIO(request)
        self.output = bytearray()
        self.timeouts = []

    def recv(self, size):
        return self.input.read(size)

    def sendall(self, data):
        self.output.extend(data)

    def settimeout(self, seconds):
        self.timeouts.append(seconds)


def response(body='héllo', status=200, headers=()):
    return {'status': status, 'headers': headers, 'body': body}


class HttpServerWire(unittest.TestCase):
    server = http_server

    def cgi(self, env=None, body=b'', handler=None):
        output, errors = io.BytesIO(), io.StringIO()
        env = {'REQUEST_METHOD': 'GET', 'REQUEST_URI': '/p?q=1', **(env or {})}
        self.server.serve_cgi(handler or (lambda req: response()), env,
                              io.BytesIO(body), output, errors)
        return output.getvalue(), errors.getvalue()

    def exchange(self, raw, handler=None):
        sock, errors = MemorySocket(raw), io.StringIO()
        self.server.serve_connection(sock, handler or (lambda req: response()),
                                     stderr=errors)
        return bytes(sock.output), errors.getvalue()

    def test_cgi_exact_unicode_and_head(self):
        expected = b'Status: 200 OK\r\nContent-Length: 6\r\n\r\nh\xc3\xa9llo'
        self.assertEqual(self.cgi()[0], expected)
        self.assertEqual(self.cgi({'REQUEST_METHOD': 'HEAD'})[0],
                         expected[:-6])

    def test_cgi_request_fields_and_sorted_headers(self):
        requests = []

        def handle(req):
            requests.append(req)
            return response('')

        self.cgi({'REQUEST_METHOD': 'post', 'REQUEST_URI': '/raw%2F?q=old',
                  'QUERY_STRING': 'q=a+b', 'CONTENT_LENGTH': '2',
                  'CONTENT_TYPE': ' text/plain\t', 'HTTP_X_Z': 'z',
                  'HTTP_X_A': ' a '}, b'\xc3\xa9', handle)
        self.assertEqual(requests, [{
            'method': 'post', 'target': '/raw%2F', 'query': 'q=a+b',
            'headers': (('content-length', '2'),
                        ('content-type', 'text/plain'),
                        ('x-a', 'a'), ('x-z', 'z')), 'body': 'é'}])

    def test_cgi_rejections_skip_handler(self):
        def unused(req):
            self.fail('request rejection called handler')

        cases = [({'CONTENT_LENGTH': '1'}, b'\xff', 400),
                 ({'CONTENT_LENGTH': '8388609'}, b'', 413),
                 ({'CONTENT_LENGTH': '-1'}, b'', 400),
                 ({'REQUEST_URI': 'https://example.com/'}, b'', 400),
                 ({'REQUEST_URI': '/\udcff'}, b'', 400),
                 ({'QUERY_STRING': '\udcff'}, b'', 400),
                 ({'REQUEST_URI': 'absolute', 'CONTENT_LENGTH': '8388609'},
                  b'', 400),
                 ({'REQUEST_METHOD': '', 'CONTENT_LENGTH': '8388609'},
                  b'', 400),
                 ({'HTTP_': 'bad'}, b'', 400)]
        for env, body, status in cases:
            with self.subTest(env=env):
                self.assertTrue(self.cgi(env, body, unused)[0].startswith(
                    f'Status: {status} '.encode()))
        out = io.BytesIO()
        self.server.serve_cgi(unused, {'REQUEST_METHOD': 'GET'}, io.BytesIO(),
                              out, io.StringIO())
        self.assertEqual(out.getvalue(),
                         b'Status: 500 Internal Server Error\r\n'
                         b'Content-Length: 0\r\n\r\n')

    def test_response_validation_before_any_output(self):
        cases = [response('x', 204), response('x', 205), response('x', 304),
                 response('', 199), response('', 600),
                 response(headers=(('content-LENGTH', '0'),)),
                 response(headers=(('X', 'a\rb'),)),
                 response(headers=(('X', 'é'),)),
                 response(headers=(('bad name', 'x'),))]
        for value in cases:
            with self.subTest(value=value):
                out, _ = self.cgi(handler=lambda req: value)
                self.assertEqual(out, b'Status: 500 Internal Server Error\r\n'
                                 b'Content-Length: 0\r\n\r\n')

    def test_fault_diagnostic_and_stdout_isolation(self):
        def handle(req):
            print('handler output')
            raise RuntimeError('test fault')

        out, err = self.cgi(handler=handle)
        self.assertEqual(out, b'Status: 500 Internal Server Error\r\n'
                         b'Content-Length: 0\r\n\r\n')
        self.assertIn('handler output', err)
        self.assertEqual(json.loads(err.splitlines()[-1])['code'], 'E-SERVE')

    def test_listener_fields_order_head_and_expect(self):
        requests = []

        def handle(req):
            requests.append(req)
            return response('é', headers=(('X-Answer', 'yes'),))

        raw = (b'POST /raw%2F?a+b HTTP/1.1\r\nX-Z: a\r\nX-A: b\r\n'
               b'X-Z: c\r\nContent-Length: 2\r\n'
               b'Expect: 100-continue\r\n\r\n\xc3\xa9')
        out, _ = self.exchange(raw, handle)
        self.assertEqual(out, b'HTTP/1.1 100 Continue\r\n\r\n'
                         b'HTTP/1.1 200 OK\r\nX-Answer: yes\r\n'
                         b'Content-Length: 2\r\nConnection: close\r\n\r\n'
                         b'\xc3\xa9')
        self.assertEqual(requests[0]['headers'][:3],
                         (('x-z', 'a'), ('x-a', 'b'), ('x-z', 'c')))
        self.assertEqual(requests[0]['body'], 'é')
        out, _ = self.exchange(b'HEAD / HTTP/1.0\r\n\r\n', handle)
        self.assertTrue(out.endswith(b'Content-Length: 2\r\n'
                                    b'Connection: close\r\n\r\n'))

    def test_all_listener_rejections(self):
        def unused(req):
            self.fail('request rejection called handler')

        cases = [(b'GET / HTTP/2\r\n\r\n', 505),
                 (b'CONNECT / HTTP/1.1\r\n\r\n', 501),
                 (b'GET / HTTP/1.1\r\nTransfer-Encoding: x\r\n\r\n', 501),
                 (b'GET / HTTP/1.1\r\nTransfer-Encoding: x\r\n'
                  b'Content-Length: 0\r\n\r\n', 400),
                 (b'GET / HTTP/1.1\r\nContent-Length: 0\r\n'
                  b'Content-Length: 0\r\n\r\n', 400),
                 (b'GET / HTTP/1.1\r\nContent-Length: x\r\n\r\n', 400),
                 (b'GET / HTTP/1.1\r\nContent-Length: 8388609\r\n\r\n', 413),
                 (b'GET / HTTP/1.1\r\n' + b'X: a\r\n' * 101 + b'\r\n', 431),
                 (b'GET / HTTP/1.1\r\nX: ' + b'a' * 65536 + b'\r\n\r\n', 431),
                 (b'GET / HTTP/1.1\r\nContent-Length: 1\r\n\r\n\xff', 400),
                 (b'GET /\xff HTTP/1.1\r\n\r\n', 400),
                 (b'GET bad HTTP/1.1\r\nContent-Length: 8388609\r\n\r\n',
                  413),
                 (b'CONNECT / HTTP/2\r\n\r\n', 505),
                 (b'CONNECT / HTTP/1.1\r\n' + b'X: a\r\n' * 101 + b'\r\n',
                  501),
                 (b'GET / HTTP/1.1\n\r\n\r\n', 505),
                 (b'GET / HTTP/1.1\r\nX: a\n\r\n\r\n', 400)]
        for raw, status in cases:
            with self.subTest(status=status, raw=raw[:80]):
                out, _ = self.exchange(raw, unused)
                self.assertTrue(out.startswith(f'HTTP/1.1 {status} '.encode()),
                                out)

    def test_header_size_and_count_exact_boundaries(self):
        prefix, suffix = b'GET / HTTP/1.1\r\nX: ', b'\r\n\r\n'
        exact = prefix + b'a' * (65536 - len(prefix + suffix)) + suffix
        self.assertEqual(len(exact), 65536)
        for raw in (exact, b'GET / HTTP/1.1\r\n' + b'X: a\r\n' * 100
                    + b'\r\n'):
            out, _ = self.exchange(raw)
            self.assertTrue(out.startswith(b'HTTP/1.1 200 OK\r\n'), out)
        out, _ = self.exchange(exact[:-4] + b'a\r\n\r\n')
        self.assertTrue(out.startswith(b'HTTP/1.1 431 '), out)

    def test_no_body_statuses_headers_and_reason_labels(self):
        for code in (204, 205, 304):
            out, _ = self.cgi(handler=lambda req: response('', code))
            self.assertTrue(out.endswith(b'Content-Length: 0\r\n\r\n'))
            self.assertTrue(out.startswith(f'Status: {code} '.encode()))
        out, _ = self.cgi(handler=lambda req: response(
            '', 299, (('X-Case', 'first'), ('x-case', '\tsecond '))))
        self.assertEqual(out, b'Status: 299 Unknown\r\nX-Case: first\r\n'
                         b'x-case: \tsecond \r\nContent-Length: 0\r\n\r\n')
        for code, phrase in ((413, 'Request Entity Too Large'),
                             (414, 'Request URI Too Long'),
                             (416, 'Requested Range Not Satisfiable'),
                             (418, "I'm a teapot"),
                             (422, 'Unprocessable Entity')):
            out, _ = self.cgi(handler=lambda req: response('', code))
            self.assertTrue(out.startswith(f'Status: {code} {phrase}\r\n'
                                           .encode()))

    def test_absolute_deadlines_and_timeout_response_can_be_sent(self):
        # Internal monotonic-clock hooks avoid sleeps and never ship as knobs.
        cases = [(b'GET / HTTP/1.1\r\n', [0.0, 10.1]),
                 (b'POST / HTTP/1.1\r\nContent-Length: 1\r\n\r\n',
                  [0.0, 0.1, 30.1])]
        for raw, ticks in cases:
            with patch.object(self.server.time, 'monotonic',
                              side_effect=ticks):
                out, _ = self.exchange(raw)
            self.assertTrue(out.startswith(b'HTTP/1.1 408 '), out)

    def test_header_recv_finishing_after_deadline_is_rejected(self):
        # A recv may return bytes at the deadline; completing the header does
        # not exempt it from the absolute 10-second limit.
        with patch.object(self.server.time, 'monotonic',
                          side_effect=[0.0, 0.1, 10.1]):
            out, _ = self.exchange(b'GET / HTTP/1.1\r\n\r\n')
        self.assertTrue(out.startswith(b'HTTP/1.1 408 '), out)

    def test_body_recv_finishing_after_total_deadline_is_rejected(self):
        headers = b'POST / HTTP/1.1\r\nContent-Length: 1\r\n\r\n'
        with patch.object(MemorySocket, 'recv', side_effect=[headers, b'x']):
            with patch.object(self.server.time, 'monotonic',
                              side_effect=[0.0, 0.1, 0.2, 0.3, 30.1]):
                out, _ = self.exchange(b'')
        self.assertTrue(out.startswith(b'HTTP/1.1 408 '), out)

    def test_request_header_values_keep_latin1_and_reject_controls(self):
        requests = []

        def handle(req):
            requests.append(req)
            return response('')

        for byte in range(256):
            with self.subTest(byte=byte):
                raw = (b'GET / HTTP/1.1\r\nX: ' + bytes([byte])
                       + b'\r\n\r\n')
                out, _ = self.exchange(raw, handle)
                valid = byte >= 32 and byte != 127 or byte == 9
                code = 200 if valid else 400
                self.assertTrue(out.startswith(f'HTTP/1.1 {code} '.encode()),
                                out)
                if valid:
                    self.assertEqual(requests[-1]['headers'],
                                     (('x', chr(byte).strip(' \t')),))

    def test_deadline_and_public_validation_without_binding(self):
        self.assertEqual(self.server.SERVER_HEADER_TIMEOUT, 10.0)
        self.assertEqual(self.server.SERVER_TOTAL_TIMEOUT, 30.0)
        with patch.object(MemorySocket, 'recv', side_effect=TimeoutError):
            out, _ = self.exchange(b'')
        self.assertIn(b'HTTP/1.1 408 Request Timeout', out)
        with patch.object(self.server.socket, 'socket') as create:
            with self.assertRaises(ValueError):
                self.server.serve_listener(lambda req: response(),
                                           host='0.0.0.0')
            create.assert_not_called()


class EmbeddedHttpServerWire(HttpServerWire):
    """The exact source embedded by --target py has the same wire contract."""
    @classmethod
    def setUpClass(cls):
        source = Path(http_server.__file__).read_text(encoding='utf-8')
        namespace = {}
        exec(wrap_module(source, 'server'), namespace)
        cls.server = namespace['server']


class ServeTransportErrors(unittest.TestCase):
    def test_interpreter_bind_failure_has_usage_exit(self):
        errors = io.StringIO()
        fixture = (Path(__file__).resolve().parents[1]
                   / 'spec/http-server/handler.lm')
        with patch.object(http_server.socket, 'socket',
                          side_effect=OSError('test bind failure')):
            with patch.object(sys, 'stderr', errors):
                code = cli_serve.cmd_serve(['handler.handle', str(fixture)])
        self.assertEqual(code, 2)
        self.assertIn('test bind failure', errors.getvalue())

    def test_built_python_bind_failure_has_usage_exit(self):
        errors = io.StringIO()
        namespace = {'sys': sys, 'seed_from_env': lambda: None,
                     'parse_serve_args': parse_serve_args,
                     'server_mod': SimpleNamespace(
                         serve_listener=self.raise_bind_error)}
        source = (Path(http_server.__file__).parent
                  / 'runtime/py/serve.py').read_text(encoding='utf-8')
        exec(source, namespace)
        with patch.object(sys, 'argv', ['server.py', '--listen']):
            with patch.object(sys, 'stderr', errors):
                with self.assertRaises(SystemExit) as stopped:
                    namespace['run_serve'](lambda req: None, -1)
        self.assertEqual(stopped.exception.code, 2)
        self.assertIn('test bind failure', errors.getvalue())

    @staticmethod
    def raise_bind_error(*args, **kwargs):
        raise OSError('test bind failure')


if __name__ == '__main__':
    unittest.main()
