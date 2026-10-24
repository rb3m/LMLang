"""Raw HTTPS dependency downloads using the runtime HTTP transport and limits."""
from http.client import HTTPException
import ssl
import time

from . import http_prims as http


def download_bytes(url):
    sock = response = None
    try:
        deadline = time.monotonic() + http.HTTP_TOTAL_TIMEOUT
        _, parsed, host, port, target, _ = http._validate('GET', url, (), '')
        if parsed.scheme != 'https':
            raise ValueError('dependency URL must use HTTPS')
        sock = http._connect(host, port or 443, deadline)
        sock.settimeout(http._remaining(deadline))
        sock = http._system_tls().wrap_socket(sock, server_hostname=host)
        sock.settimeout(http._remaining(deadline))
        sock.sendall((f'GET {target} HTTP/1.1\r\nHost: {parsed.netloc}\r\n'
                      'Connection: close\r\nContent-Length: 0\r\n\r\n').encode('ascii'))
        response = http._Response(sock, deadline, 'GET')
        response.begin()
        if response.status != 200:
            raise ValueError(f'HTTP status {response.status}; expected 200 (redirects refused)')
        expected = response.length
        if expected is not None and expected > http.HTTP_BODY_LIMIT:
            raise ValueError('download exceeds 8 MiB')
        chunks, size = [], 0
        while True:
            chunk = response.read(min(65536, http.HTTP_BODY_LIMIT + 1 - size))
            size += len(chunk)
            if size > http.HTTP_BODY_LIMIT:
                raise ValueError('download exceeds 8 MiB')
            if not chunk:
                break
            chunks.append(chunk)
        if expected is not None and size != expected:
            raise ValueError('incomplete HTTP response')
        http._remaining(deadline)
        return b''.join(chunks)
    except http._HttpProblem as ex:
        raise ValueError(f'HTTP download failed: {ex}') from None
    except (OSError, ssl.SSLError, HTTPException) as ex:
        raise ValueError(f'HTTP download failed: {type(ex).__name__}') from None
    finally:
        if response is not None:
            response.close()
        if sock is not None:
            sock.close()
