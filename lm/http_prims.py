"""Bounded HTTP/1 client shared by the interpreter and Python target."""
from __future__ import annotations

import http.client
import io
import ipaddress
import os
import queue
import re
import socket
import ssl
import threading
import time
from urllib.parse import urlsplit

from .values import LmFail, Pair, Rec

HTTP_TOTAL_TIMEOUT = 30.0
HTTP_CONNECT_TIMEOUT = 5.0
HTTP_BODY_LIMIT = 8 * 1024 * 1024
HTTP_HEADER_LIMIT = 64 * 1024
HTTP_HEADER_FIELDS = 100
_TOKEN = re.compile(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+\Z")
_METHODS = {'GET', 'HEAD', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS'}
_FORBIDDEN = {'host', 'content-length', 'transfer-encoding', 'connection'}


class _HttpProblem(Exception):
    pass


def _remaining(deadline):
    seconds = deadline - time.monotonic()
    if seconds <= 0:
        raise TimeoutError
    return seconds


def _validate(method, url, headers, body):
    if (any(ord(c) <= 32 or ord(c) >= 127 for c in url)
            or '#' in url or '\\' in url):
        raise _HttpProblem('invalid-request')
    try:
        parsed = urlsplit(url)
        host = parsed.hostname
        port = parsed.port
        if (parsed.scheme not in ('http', 'https') or not host
                or parsed.username is not None or parsed.password is not None
                or '%' in host or not host.isascii()):
            raise ValueError
        authority = parsed.netloc
        if authority.startswith('['):
            suffix = authority.rsplit(']', 1)[-1]
        else:
            suffix = (':' + authority.split(':', 1)[1]
                      if ':' in authority else '')
        if suffix and (not suffix.startswith(':')
                       or not re.fullmatch(r':[0-9]+', suffix)):
            raise ValueError
        if port is not None and not 1 <= port <= 65535:
            raise ValueError
        try:
            addr = ipaddress.ip_address(host)
        except ValueError:
            addr = None
        loopback = host == 'localhost' or (
            addr is not None and (addr == ipaddress.ip_address('::1')
                                  or addr.version == 4 and addr.is_loopback))
        if parsed.scheme == 'http' and not loopback:
            raise ValueError
        query = '?' + parsed.query if '?' in url else ''
        target = (parsed.path or '/') + query
        # URI paths are ASCII on the wire; percent-encode non-ASCII explicitly.
        target.encode('ascii')
        if re.search(r'%(?![0-9A-Fa-f]{2})', target):
            raise ValueError
    except (ValueError, UnicodeError):
        raise _HttpProblem('invalid-request') from None
    method = method.upper() if method.isascii() else ''
    if method not in _METHODS:
        raise _HttpProblem('invalid-request')
    encoded = []
    size = len(body.encode('utf-8'))
    for pair in headers:
        name, value = pair.a, pair.b
        if (not _TOKEN.fullmatch(name) or name.lower() in _FORBIDDEN
                or any(ord(c) < 32 and c != '\t' or ord(c) == 127
                       for c in value)):
            raise _HttpProblem('invalid-request')
        raw = value.encode('utf-8')
        size += len(name) + len(raw)
        encoded.append((name, raw))
    if size > HTTP_BODY_LIMIT:
        raise _HttpProblem('limit')
    return method, parsed, host, port, target, encoded


def _system_tls():
    """Load the system trust paths, ignoring SSL_CERT_FILE/SSL_CERT_DIR."""
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    paths = ssl.get_default_verify_paths()
    cafile = paths.openssl_cafile
    capath = paths.openssl_capath
    if os.name == 'nt':
        for store in ('CA', 'ROOT'):
            for cert, encoding, trust in ssl.enum_certificates(store):
                if encoding == 'x509_asn' and (
                        trust is True or ssl.Purpose.SERVER_AUTH.oid in trust):
                    context.load_verify_locations(cadata=cert)
    if ((cafile and os.path.isfile(cafile))
            or (capath and os.path.isdir(capath))):
        context.load_verify_locations(
            cafile if cafile and os.path.isfile(cafile) else None,
            capath if capath and os.path.isdir(capath) else None)
    return context


def _addresses(host, port, deadline):
    if host == 'localhost':
        return [(socket.AF_INET, socket.SOCK_STREAM, 0, '',
                 ('127.0.0.1', port)),
                (socket.AF_INET6, socket.SOCK_STREAM, 0, '',
                 ('::1', port, 0, 0))]
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        addr = None
    if addr is not None:
        family = socket.AF_INET if addr.version == 4 else socket.AF_INET6
        return [(family, socket.SOCK_STREAM, 0, '', (host, port))]
    result = queue.Queue(maxsize=1)

    def resolve():
        try:
            result.put(socket.getaddrinfo(host, port, type=socket.SOCK_STREAM))
        except (OSError, UnicodeError, ValueError) as ex:
            result.put(ex)

    threading.Thread(target=resolve, daemon=True).start()
    try:
        addresses = result.get(timeout=_remaining(deadline))
    except queue.Empty:
        raise TimeoutError from None
    if isinstance(addresses, Exception):
        raise _HttpProblem('dns') from None
    return addresses


def _connect(host, port, deadline):
    connect_deadline = min(deadline, time.monotonic() + HTTP_CONNECT_TIMEOUT)
    addresses = _addresses(host, port, connect_deadline)
    for family, kind, proto, _, address in addresses:
        sock = socket.socket(family, kind, proto)
        try:
            sock.settimeout(_remaining(connect_deadline))
            sock.connect(address)
            return sock
        except OSError as ex:
            sock.close()
            if isinstance(ex, TimeoutError):
                raise
    raise _HttpProblem('connect')


class _DeadlineReader(io.RawIOBase):
    def __init__(self, sock, deadline):
        self.sock, self.deadline = sock, deadline

    def readable(self):
        return True

    def readinto(self, buffer):
        self.sock.settimeout(_remaining(self.deadline))
        return self.sock.recv_into(buffer)


class _Response(http.client.HTTPResponse):
    """Use stdlib framing with bounded headers (including 100 fields)."""
    def __init__(self, sock, deadline, method):
        # HTTPResponse expects makefile; our reader applies the total deadline
        # on every recv, so a trickle cannot renew an inactivity timeout.
        class Source:
            def makefile(self, mode):
                return io.BufferedReader(_DeadlineReader(sock, deadline))
        super().__init__(Source(), method=method)
        self.header_bytes = 0
        self.header_fields = 0

    def _fields(self):
        pairs = []
        while True:
            line = self.fp.readline(HTTP_HEADER_LIMIT + 1)
            if line in (b'\r\n', b'\n'):
                return pairs
            if not line:
                raise _HttpProblem('connect')
            self.header_bytes += len(line)
            self.header_fields += 1
            if (self.header_bytes > HTTP_HEADER_LIMIT
                    or self.header_fields > HTTP_HEADER_FIELDS):
                raise _HttpProblem('limit')
            name, sep, value = line.rstrip(b'\r\n').partition(b':')
            if not sep or not _TOKEN.fullmatch(name.decode('latin-1')):
                raise _HttpProblem('connect')
            value = value.strip(b' \t').decode('latin-1')
            if any(ord(c) < 32 and c != '\t' or ord(c) == 127 for c in value):
                raise _HttpProblem('connect')
            pairs.append((name.decode('ascii').lower(), value))

    def _read_and_discard_trailer(self):
        self._fields()

    def begin(self):
        while True:
            version, status, reason = self._read_status()
            self.raw_headers = self._fields()
            if not 100 <= status < 200 or status == 101:
                break
        self.code = self.status = status
        self.reason = reason.strip()
        self.version = 10 if version == 'HTTP/1.0' else 11
        self.headers = self.msg = http.client.HTTPMessage()
        for name, value in self.raw_headers:
            self.headers[name] = value
        encoding = self.headers.get('transfer-encoding', '').lower()
        self.chunked = encoding == 'chunked'
        self.chunk_left = None
        self.will_close = self._check_close()
        self.length = None
        lengths = self.headers.get_all('content-length', [])
        if lengths and not self.chunked:
            if (len(set(lengths)) != 1
                    or not re.fullmatch(r'[0-9]+', lengths[0])):
                raise _HttpProblem('connect')
            self.length = int(lengths[0])
        if (self._method == 'HEAD' or status in (204, 304)
                or 100 <= status < 200):
            self.length = 0
            self.chunked = False
        if not self.chunked and self.length is None:
            self.will_close = True


def http_request(it, method, url, headers, body):
    sock = None
    response = None
    try:
        deadline = time.monotonic() + HTTP_TOTAL_TIMEOUT
        method, parsed, host, port, target, headers = _validate(
            method, url, headers, body)
        port = port or (443 if parsed.scheme == 'https' else 80)
        sock = _connect(host, port, deadline)
        if parsed.scheme == 'https':
            sock.settimeout(_remaining(deadline))
            sock = _system_tls().wrap_socket(sock, server_hostname=host)
        raw_body = body.encode('utf-8')
        request = [f'{method} {target} HTTP/1.1\r\n'.encode('ascii'),
                   b'Host: ' + parsed.netloc.encode('ascii') + b'\r\n',
                   b'Connection: close\r\n',
                   f'Content-Length: {len(raw_body)}\r\n'.encode('ascii')]
        request.extend(name.encode('ascii') + b': ' + value + b'\r\n'
                       for name, value in headers)
        sock.settimeout(_remaining(deadline))
        sock.sendall(b''.join(request) + b'\r\n' + raw_body)
        response = _Response(sock, deadline, method)
        response.begin()
        expected = response.length
        if expected is not None and expected > HTTP_BODY_LIMIT:
            raise _HttpProblem('limit')
        chunks, size = [], 0
        while True:
            chunk = response.read(min(65536, HTTP_BODY_LIMIT + 1 - size))
            size += len(chunk)
            if size > HTTP_BODY_LIMIT:
                raise _HttpProblem('limit')
            if not chunk:
                break
            chunks.append(chunk)
        if expected is not None and size != expected:
            raise _HttpProblem('connect')
        text = b''.join(chunks).decode('utf-8')
        _remaining(deadline)
        result_headers = tuple(Pair(k, v) for k, v in sorted(
            response.raw_headers, key=lambda p: p[0]))
        return Rec('http.Response', (
            ('status', response.status), ('headers', result_headers),
            ('body', text)))
    except _HttpProblem as ex:
        category = str(ex)
    except TimeoutError:
        category = 'timeout'
    except ssl.SSLError:
        category = 'tls'
    except UnicodeError:
        category = 'invalid-utf8'
    except http.client.LineTooLong:
        category = 'limit'
    except (OSError, http.client.HTTPException, ValueError, OverflowError):
        category = 'connect'
    finally:
        if response is not None:
            response.close()
        if sock is not None:
            sock.close()
    raise LmFail('http.HttpError', (url, category)) from None


HTTP_PRIMS = {'http.request': http_request}
