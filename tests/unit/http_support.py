"""Offline HTTP fixtures; the PEM key is disposable public test data."""
from collections import Counter
from contextlib import contextmanager
from pathlib import Path
import socketserver
import ssl
import threading
import time
import unittest


LIMIT = 8 * 1024 * 1024


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, context=None):
        super().__init__(('127.0.0.1', 0), Handler)
        self.context = context
        self.paths = Counter()

    def get_request(self):
        connection, address = super().get_request()
        if self.context:
            connection = self.context.wrap_socket(connection, server_side=True)
        return connection, address


class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        try:
            self.respond()
        except (BrokenPipeError, ConnectionResetError, ssl.SSLError):
            pass

    def respond(self):
        request = self.rfile.readline().decode('ascii').split()
        if len(request) != 3:
            return
        method, path, _ = request
        headers = {}
        while True:
            line = self.rfile.readline()
            if line in (b'\r\n', b'\n', b''):
                break
            name, value = line.decode('latin1').split(':', 1)
            headers[name.lower()] = value.strip()
        body = self.rfile.read(int(headers.get('content-length', '0')))
        self.server.paths[path] += 1
        if path == '/drop':
            return
        if path == '/slow':
            time.sleep(4.0)
        if path in ('/slow-body', '/drip'):
            self.request.sendall(b'HTTP/1.1 200 OK\r\n'
                                 b'Content-Length: 5\r\n\r\n')
            if path == '/slow-body':
                time.sleep(4.0)
                self.request.sendall(b'hello')
                return
            for byte in b'hello':
                time.sleep(0.6)
                self.request.sendall(bytes([byte]))
            return
        if path == '/headers-count':
            self.request.sendall(b'HTTP/1.1 200 OK\r\n' + b'X: a\r\n' * 101
                                 + b'\r\n')
            return
        if path == '/headers-size':
            self.request.sendall(b'HTTP/1.1 200 OK\r\nX: ' + b'a' * 65536
                                 + b'\r\n\r\n')
            return
        if path == '/headers-100':
            self.request.sendall(b'HTTP/1.1 200 OK\r\n' + b'X: a\r\n' * 99
                                 + b'Content-Length: 0\r\n\r\n')
            return
        if path == '/headers-65536':
            self.request.sendall(b'HTTP/1.1 200 OK\r\nX: ' + b'a' * 65531
                                 + b'\r\n\r\n')
            return
        if path == '/chunked':
            self.request.sendall(b'HTTP/1.1 200 OK\r\n'
                                 b'Transfer-Encoding: chunked\r\n'
                                 b'\r\n2\r\n\xc3\xa9\r\n'
                                 b'5\r\nhello\r\n0\r\n\r\n')
            return
        if path == '/chunk-limit':
            self.request.sendall(b'HTTP/1.1 200 OK\r\n'
                                 b'Transfer-Encoding: chunked\r\n'
                                 b'\r\n800001\r\n' + b'a' * (LIMIT + 1)
                                 + b'\r\n0\r\n\r\n')
            return
        status, extra, payload = b'200 OK', b'', 'héllo'.encode()
        length = None
        if path == '/duplicates':
            extra = b'X-Z: first\r\nX-A: a\r\nx-z: second\r\n'
            payload = b'x'
        elif path == '/redirect':
            status, payload = b'302 Found', b''
            extra = b'Location: /redirect-target\r\n'
        elif path == '/missing':
            status, payload = b'404 Not Found', b'no'
        elif path == '/empty':
            status, payload = b'204 No Content', b''
        elif path == '/invalid-utf8':
            payload = b'\xff'
        elif path == '/truncated':
            payload, length = b'x', 10
        elif path == '/oversize':
            payload, length = b'', LIMIT + 1
        elif path == '/body-limit':
            payload = b'a' * LIMIT
        elif path == '/discard':
            payload = b''
        elif path == '/compressed':
            extra, payload = b'Content-Encoding: gzip\r\n', b'raw'
        elif path == '/cookie':
            extra, payload = b'Set-Cookie: secret=must-not-return\r\n', b''
        elif path.startswith('/echo'):
            payload = ('|'.join([method, path, body.decode('utf-8'),
                                 headers.get('x-probe', ''),
                                 headers.get('accept-encoding', ''),
                                 headers.get('cookie', '')])).encode()
        if length is None:
            length = len(payload)
        self.request.sendall(b'HTTP/1.1 ' + status + b'\r\nContent-Length: '
                             + str(length).encode() + b'\r\n'
                             + extra + b'\r\n')
        if method != 'HEAD':
            self.request.sendall(payload)


@contextmanager
def serving(tls=False):
    context = None
    if tls:
        directory = Path(__file__).with_name('http_fixtures')
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(directory / 'cert.pem', directory / 'key.pem')
    try:
        server = Server(context)
    except PermissionError as ex:
        raise unittest.SkipTest(f'host blocks loopback socket bind: {ex}') from ex
    thread = threading.Thread(target=server.serve_forever,
                              kwargs={'poll_interval': 0.02}, daemon=True)
    thread.start()
    try:
        scheme = 'https' if tls else 'http'
        yield server, scheme + '://127.0.0.1:' + str(server.server_address[1])
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
