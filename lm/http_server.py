"""Shared CGI and sequential HTTP/1 listener adapters (ADR-076)."""
from contextlib import redirect_stdout
from http import HTTPStatus
import ipaddress
import json
import os
import re
import socket
import sys
import time


SERVER_HEADER_TIMEOUT = 10.0
SERVER_TOTAL_TIMEOUT = 30.0
SERVER_HEADER_LIMIT = 64 * 1024
SERVER_HEADER_FIELDS = 100
SERVER_BODY_LIMIT = 8 * 1024 * 1024
_SERVER_TOKEN = re.compile(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+\Z")
_SERVER_FRAMING = frozenset((
    'content-length', 'transfer-encoding', 'connection', 'keep-alive',
    'upgrade', 'te', 'trailer'))


class ServerProblem(Exception):
    """An adapter rejection, handled before the LM handler is called."""
    def __init__(self, status):
        super().__init__(status)
        self.status = status


def _server_text(value):
    value.encode('utf-8', errors='strict')
    return value


def _server_target(target):
    _server_text(target)
    if (not target.startswith('/') or '#' in target
            or any(ord(c) <= 32 or ord(c) == 127 for c in target)):
        raise ServerProblem(400)
    path, _, query = target.partition('?')
    return path, query


def _server_length(value):
    if not value or value.strip('0123456789'):
        raise ServerProblem(400)
    # Avoid huge integer conversions while accepting arbitrary leading zeroes.
    digits = value.lstrip('0') or '0'
    if len(digits) > 7 or int(digits) > SERVER_BODY_LIMIT:
        raise ServerProblem(413)
    return int(digits)


def _server_header(name, value):
    if (not _SERVER_TOKEN.fullmatch(name)
            or any(ord(c) < 32 and c != '\t' or ord(c) == 127 for c in value)):
        raise ServerProblem(400)
    return name.lower(), value.strip(' \t')


def _server_request(method, target, query, headers, body):
    if not _SERVER_TOKEN.fullmatch(method):
        raise ServerProblem(400)
    path, raw_query = _server_target(target)
    query = raw_query if query is None else _server_text(query)
    return {'method': method, 'target': path, 'query': query,
            'headers': tuple(headers), 'body': body.decode('utf-8', 'strict')}


def read_cgi(environ, stdin):
    """Read one CGI request. URI and query retain their raw escapes."""
    if 'REQUEST_URI' not in environ:
        raise ServerProblem(500)
    method = environ.get('REQUEST_METHOD', '')
    uri, query = environ['REQUEST_URI'], environ.get('QUERY_STRING', '')
    request = _server_request(method, uri, query, (), b'')
    length_text = environ.get('CONTENT_LENGTH')
    length = 0 if length_text is None else _server_length(length_text)
    headers = []
    for key, value in environ.items():
        if key.startswith('HTTP_'):
            headers.append(_server_header(key[5:].replace('_', '-'), value))
        elif key in ('CONTENT_TYPE', 'CONTENT_LENGTH'):
            headers.append(_server_header(key.replace('_', '-'), value))
    headers.sort()
    body = bytearray()
    while len(body) < length:
        chunk = stdin.read(length - len(body))
        if not chunk:
            raise ServerProblem(400)
        body.extend(chunk)
    request['headers'] = tuple(headers)
    request['body'] = bytes(body).decode('utf-8', 'strict')
    return request


def _server_diagnostic(error, stderr, diagnostic):
    if diagnostic is not None:
        rendered = diagnostic(error)
    else:
        rendered = json.dumps({
            'code': 'E-SERVE', 'severity': 'error', 'file': '', 'line': 1,
            'col': 1, 'path': '',
            'msg': 'HTTP handler fault or invalid response',
            'expected': '', 'found': '', 'fix': []}, separators=(',', ':'))
    stderr.write(rendered + '\n')
    stderr.flush()


def _server_response(value):
    status, headers, body = value['status'], value['headers'], value['body']
    if type(status) is not int or not 200 <= status <= 599:
        raise ServerProblem(500)
    encoded = body.encode('utf-8', 'strict')
    if status in (204, 205, 304) and encoded:
        raise ServerProblem(500)
    fields = []
    for name, text in headers:
        if (not _SERVER_TOKEN.fullmatch(name)
                or name.lower() in _SERVER_FRAMING
                or any(c != '\t' and not 32 <= ord(c) <= 126 for c in text)):
            raise ServerProblem(500)
        fields.append((name, text))
    return status, fields, encoded


def frame_response(status, headers=(), body=b'', *, cgi=False, head=False):
    """Frame already validated fields identically to the Go adapter."""
    try:
        reason = HTTPStatus(status).phrase
    except ValueError:
        reason = 'Unknown'
    # HTTPStatus labels changed in Python 3.13. Pin Go's wire labels on every
    # supported Python rather than letting a runtime upgrade change responses.
    reason = {413: 'Request Entity Too Large', 414: 'Request URI Too Long',
              416: 'Requested Range Not Satisfiable', 418: "I'm a teapot",
              422: 'Unprocessable Entity'}.get(status, reason)
    first = 'Status: ' if cgi else 'HTTP/1.1 '
    lines = [f'{first}{status} {reason}\r\n']
    lines.extend(f'{name}: {text}\r\n' for name, text in headers)
    lines.append(f'Content-Length: {len(body)}\r\n')
    if not cgi:
        lines.append('Connection: close\r\n')
    lines.append('\r\n')
    return ''.join(lines).encode('ascii') + (b'' if head else body)


def _server_invoke(handler, request, stderr, diagnostic):
    try:
        # A handler may have io.out; it must never corrupt protocol output.
        with redirect_stdout(stderr):
            value = handler(request)
        return _server_response(value)
    except Exception as error:
        _server_diagnostic(error, stderr, diagnostic)
        return 500, (), b''


def serve_cgi(handler, environ=None, stdin=None, stdout=None, stderr=None,
              diagnostic=None):
    """Write exactly one CGI response; all handler faults become empty 500s."""
    environ = os.environ if environ is None else environ
    stdin = sys.stdin.buffer if stdin is None else stdin
    stdout = sys.stdout.buffer if stdout is None else stdout
    stderr = sys.stderr if stderr is None else stderr
    request = None
    try:
        request = read_cgi(environ, stdin)
        status, headers, body = _server_invoke(
            handler, request, stderr, diagnostic)
    except ServerProblem as error:
        status, headers, body = error.status, (), b''
    except (UnicodeError, ValueError, OSError):
        status, headers, body = 400, (), b''
    stdout.write(frame_response(status, headers, body, cgi=True,
                               head=request is not None
                               and request['method'] == 'HEAD'))
    stdout.flush()
    return 0


class _ServerReader:
    def __init__(self, sock):
        self.sock, self.buffer = sock, bytearray()
        started = time.monotonic()
        self.deadline = started + SERVER_TOTAL_TIMEOUT
        self.header_deadline = started + SERVER_HEADER_TIMEOUT

    def receive(self, size, deadline):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ServerProblem(408)
        self.sock.settimeout(remaining)
        chunk = self.sock.recv(size)
        if time.monotonic() >= deadline:
            raise ServerProblem(408)
        if not chunk:
            raise ServerProblem(400)
        self.buffer.extend(chunk)

    def headers(self):
        while True:
            end = self.buffer.find(b'\r\n\r\n')
            if end >= 0:
                if end + 4 > SERVER_HEADER_LIMIT:
                    raise ServerProblem(431)
                result = bytes(self.buffer[:end])
                del self.buffer[:end + 4]
                return result
            if len(self.buffer) >= SERVER_HEADER_LIMIT:
                raise ServerProblem(431)
            self.receive(min(4096, SERVER_HEADER_LIMIT - len(self.buffer)),
                         min(self.deadline, self.header_deadline))

    def body(self, length):
        while len(self.buffer) < length:
            self.receive(min(65536, length - len(self.buffer)), self.deadline)
        if time.monotonic() > self.deadline:
            raise ServerProblem(408)
        return bytes(self.buffer[:length])


def read_request(sock):
    """Parse the deliberately restricted HTTP profile without a web server."""
    reader = _ServerReader(sock)
    lines = reader.headers().split(b'\r\n')
    first = lines[0].split(b' ')
    if len(first) != 3:
        raise ServerProblem(400)
    method, target, version = first
    if version not in (b'HTTP/1.0', b'HTTP/1.1'):
        raise ServerProblem(505)
    method = method.decode('ascii', 'strict')
    if not _SERVER_TOKEN.fullmatch(method):
        raise ServerProblem(400)
    if method == 'CONNECT':
        raise ServerProblem(501)
    if len(lines) - 1 > SERVER_HEADER_FIELDS:
        raise ServerProblem(431)
    headers = []
    for line in lines[1:]:
        name, colon, value = line.partition(b':')
        if not colon:
            raise ServerProblem(400)
        headers.append(_server_header(name.decode('ascii', 'strict'),
                                      value.decode('latin-1')))
    lengths = [v for k, v in headers if k == 'content-length']
    transfer = any(k == 'transfer-encoding' for k, _ in headers)
    if transfer and lengths:
        raise ServerProblem(400)
    if transfer:
        raise ServerProblem(501)
    if len(lengths) > 1:
        raise ServerProblem(400)
    length = _server_length(lengths[0]) if lengths else 0
    target = target.decode('utf-8', 'strict')
    _server_target(target)
    if any(k == 'expect' and v.lower() == '100-continue' for k, v in headers):
        remaining = reader.deadline - time.monotonic()
        if remaining <= 0:
            raise ServerProblem(408)
        sock.settimeout(remaining)
        sock.sendall(b'HTTP/1.1 100 Continue\r\n\r\n')
    return _server_request(method, target, None, headers, reader.body(length))


def serve_connection(sock, handler, stderr=None, diagnostic=None):
    """Serve one socket, keeping listener faults local to this request."""
    stderr = sys.stderr if stderr is None else stderr
    request = None
    try:
        request = read_request(sock)
        status, headers, body = _server_invoke(
            handler, request, stderr, diagnostic)
    except ServerProblem as error:
        status, headers, body = error.status, (), b''
    except TimeoutError:
        status, headers, body = 408, (), b''
    except (UnicodeError, ValueError, OSError):
        status, headers, body = 400, (), b''
    try:
        sock.settimeout(SERVER_TOTAL_TIMEOUT)
        sock.sendall(frame_response(status, headers, body,
                                   head=request is not None
                                   and request['method'] == 'HEAD'))
    except OSError:
        pass


def validate_bind(host, port, public=False):
    """Reject public exposure before creating a listening socket."""
    if type(port) is not int or not 0 <= port <= 65535:
        raise ValueError('port must be between 0 and 65535')
    try:
        loopback = ipaddress.ip_address(host).is_loopback
    except ValueError:
        loopback = host == 'localhost'
    if not public and not loopback:
        raise ValueError('non-loopback host requires --public')


def serve_listener(handler, host='127.0.0.1', port=8080, public=False,
                   stderr=None, diagnostic=None):
    """Run a sequential listener. No transport settings come from the env."""
    validate_bind(host, port, public)
    stderr = sys.stderr if stderr is None else stderr
    family = socket.AF_INET6 if ':' in host else socket.AF_INET
    with socket.socket(family, socket.SOCK_STREAM) as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind((host, port))
        listener.listen()
        actual_port = listener.getsockname()[1]
        address = (f'[{host}]:{actual_port}' if ':' in host
                   else f'{host}:{actual_port}')
        stderr.write(f'listening on http://{address}\n')
        stderr.flush()
        while True:
            connection, _ = listener.accept()
            with connection:
                serve_connection(connection, handler, stderr, diagnostic)
