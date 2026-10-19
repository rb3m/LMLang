"""Offline HTTP contracts shared unchanged by interpreter and both targets."""
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from http_support import LIMIT, serving
from lm.build import find_go, go_build
from lm.values import LmFail, show


ROOT = Path(__file__).resolve().parents[2]


def environment():
    env = {**os.environ, 'PYTHONPATH': str(ROOT)}
    for name in ('HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'http_proxy',
                 'https_proxy', 'all_proxy'):
        env[name] = 'http://127.0.0.1:1'
    env['NO_PROXY'] = env['no_proxy'] = ''
    certificates = Path(__file__).with_name('http_fixtures')
    for name in ('SSL_CERT_FILE', 'CURL_CA_BUNDLE', 'REQUESTS_CA_BUNDLE'):
        env[name] = str(certificates / 'cert.pem')
    env['SSL_CERT_DIR'] = str(certificates)
    return env


def cli(*args, cwd=ROOT):
    return subprocess.run([sys.executable, '-m', 'lm', *args], cwd=cwd,
                          env=environment(), capture_output=True, timeout=90)


def source(base, secure):
    """Each boolean assertion prints a numbered result in every backend."""
    forms = []

    def check(expression):
        number = len(forms) + 1
        forms.append('(io.print (if ' + expression + ' "ok '
                     + str(number) + '" "BAD ' + str(number) + '"))')

    def request(method, url, headers='(list)', body='""'):
        return ('(http.request ' + show(method) + ' ' + show(url) + ' '
                + headers + ' ' + body + ')')

    def fetch(path):
        return '(http.fetch ' + show(base + path) + ')'

    def failed(method, url, category, headers='(list)', body='""'):
        return ('(bad ' + show(method) + ' ' + show(url) + ' ' + headers
                + ' ' + body + ' ' + show(category) + ')')

    check('(= (get ' + fetch('/ok') + ' body) "héllo")')
    check('(= (get ' + fetch('/missing') + ' status) 404)')
    check('(= (get ' + fetch('/empty') + ' body) "")')
    check('(= (get ' + request('head', base + '/ok') + ' body) "")')
    check('(= (get ' + fetch('/chunked') + ' body) "éhello")')
    check('(= (get ' + fetch('/compressed') + ' body) "raw")')
    check('(= (str.length (get ' + fetch('/body-limit') + ' body)) 8388608)')
    check('(= (get ' + fetch('/headers-100') + ' status) 200)')
    check('(= (get ' + fetch('/headers-65536') + ' status) 200)')
    limit_request = request('POST', base + '/discard',
                            body='(str.repeat "a" 8388608)')
    check('(= (get ' + limit_request + ' status) 200)')
    check('(= (get ' + request('POST', base + '/discard',
                              '(list (pair "X" "a"))',
                              '(str.repeat "a" 8388606)') + ' status) 200)')
    check('(= (get ' + fetch('/duplicates') + ' headers) '
          '(list (pair "content-length" "1") (pair "x-a" "a") '
          '(pair "x-z" "first") (pair "x-z" "second")))')
    check('(= (get ' + fetch('/redirect') + ' status) 302)')
    check('(= (get ' + fetch('/cookie') + ' body) "")')
    for method in ('get', 'post', 'put', 'patch', 'delete', 'options'):
        call = request(method, base + '/echo?q=1',
                       '(list (pair "X-Probe" "sent"))', '"é"')
        check('(= (get ' + call + ' body) '
              + show(method.upper() + '|/echo?q=1|é|sent||') + ')')
    localhost = base.replace('127.0.0.1', 'localhost')
    check('(= (get ' + request('GET', localhost + '/ok') + ' body) "héllo")')
    for path, category in [('/invalid-utf8', 'invalid-utf8'),
                           ('/truncated', 'connect'), ('/drop', 'connect'),
                           ('/oversize', 'limit'), ('/chunk-limit', 'limit'),
                           ('/headers-count', 'limit'),
                           ('/headers-size', 'limit'), ('/slow', 'timeout'),
                           ('/slow-body', 'timeout'), ('/drip', 'timeout')]:
        check(failed('GET', base + path, category))
    check(failed('GET', secure + '/ok', 'tls'))
    invalid_urls = ['ftp://127.0.0.1/', 'file:///etc/passwd',
                    'http://example.com/', 'http://192.0.2.1/',
                    'http://localhost.evil/', 'http://[::2]/',
                    'http://127.0.0.1:0/', 'http://127.0.0.1:65536/',
                    'http://127.0.0.1:bad/', 'http:///missing',
                    'http://', 'http://user:secret@127.0.0.1/',
                    base + '/#fragment', base + '/#', base + '/\x00',
                    base + '/\r\nInjected: secret']
    for url in invalid_urls:
        check(failed('GET', url, 'invalid-request'))
    for method in ('CONNECT', 'TRACE', 'BREW', '', ' GET', 'GET\r\n'):
        check(failed(method, base + '/unused', 'invalid-request'))
    for name, value in [('Host', 'elsewhere'), ('Content-Length', '1'),
                        ('Transfer-Encoding', 'chunked'),
                        ('cOnNeCtIoN', 'close'), ('bad name', 'x'),
                        ('', 'x'), ('bad:name', 'x'), ('x\0', 'x'),
                        ('x\r\nInjected', 'x'), ('X', 'a\rb'),
                        ('X', 'a\nb'), ('X', 'a\0b')]:
        header = '(list (pair ' + show(name) + ' ' + show(value) + '))'
        check(failed('GET', base + '/unused', 'invalid-request', header))
    check(failed('POST', base + '/unused', 'limit',
                 body='(str.repeat "a" 8388609)'))
    check(failed('POST', base + '/unused', 'limit',
                 '(list (pair "X" "a"))', '(str.repeat "a" 8388608)'))
    check(failed('POST', base + '/unused', 'limit',
                 '(list (pair "X" (str.repeat "a" 8388608)))'))
    text = ('(module http-probe (purpose "Exercise HTTP in every target.") '
            '(use http io str) '
            '(fn bad (purpose "Catch an HTTP category and original URL.") '
            '(sig (method Str) (url Str) (headers (List (Pair Str Str))) '
            '(body-text Str) (category Str) -> Bool) (eff net.http) '
            '(body (try (let ((ignored '
            '(http.request method url headers body-text))) false) '
            '(catch http.HttpError (failed-url msg) '
            '(and (= failed-url url) (= msg category)))))) '
            '(fn main (purpose "Print every check result.") (sig -> Int) '
            '(eff net.http io.out) (fails http.HttpError) '
            '(body (do ' + ' '.join(forms) + ' 0))))')
    expected = ''.join('ok ' + str(i) + '\n' for i in range(1, len(forms) + 1))
    return text, expected.encode()


class HttpClient(unittest.TestCase):
    def test_effect_permission(self):
        p = cli('run', 'http.fetch', '"http://127.0.0.1:1/"')
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertEqual(json.loads(p.stderr)['code'], 'E-EFFECT-DENIED')

    def test_closed_scenario_effect(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / 'src').mkdir()
            (root / 'tests/accept').mkdir(parents=True)
            (root / 'src/demo.lm').write_text(
                '(module demo (purpose "Declare network access.") '
                '(fn main (purpose "Return one.") (sig -> Int) '
                '(eff net.http) (body 1)))')
            (root / 'tests/accept/demo.accept').write_text(
                '(scenarios (scenario "Network permission" (status proposed) '
                '(why "Validate the declared effect without network access.") '
                '(allow net.http) (run demo.main) (expect 1)))')
            p = cli('check', cwd=root)
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)

    def test_fixed_deadlines_and_offline_dns(self):
        from lm import http_prims
        self.assertEqual(http_prims.HTTP_CONNECT_TIMEOUT, 5.0)
        self.assertEqual(http_prims.HTTP_TOTAL_TIMEOUT, 30.0)
        error = socket.gaierror('private')
        url = 'https://offline.invalid/'
        with patch('socket.getaddrinfo', side_effect=error):
            with self.assertRaises(LmFail) as caught:
                http_prims.http_request(None, 'GET', url, (), '')
        self.assertEqual(caught.exception.args_, (url, 'dns'))

    def differential(self, target):
        with tempfile.TemporaryDirectory() as td, \
                serving() as (server, base), serving(tls=True) as (_, secure):
            root = Path(td)
            (root / 'src').mkdir()
            src = root / 'src/http-probe.lm'
            text, expected = source(base, secure)
            src.write_text(text)
            operation = json.dumps({'op': 'fmt', 'file': str(src)})
            p = cli('edit', 'apply', operation, cwd=root)
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
            if target == 'interp':
                # Test-only patch; neither LM nor a binary has a knob.
                driver = ('import socket,sys; import lm.http_prims as h; '
                          'h.HTTP_TOTAL_TIMEOUT = 1.5; '
                          'original = socket.getaddrinfo\n'
                          'def guarded(host, *args, **kwargs):\n'
                          ' if host == "localhost":\n'
                          '  raise AssertionError("localhost DNS")\n'
                          ' return original(host, *args, **kwargs)\n'
                          'socket.getaddrinfo = guarded\n'
                          'from lm.cli import main\nsys.exit(main())')
                command = [sys.executable, '-c', driver, 'run',
                           'http-probe.main',
                           '--allow', 'net.http', '--allow', 'io.out']
                expected += b'0\n'
            else:
                output = root / ('probe.py' if target == 'py' else 'probe')
                args = ['build', '--target', target, 'http-probe.main',
                        str(src), '-o', str(output)]
                if target == 'go':
                    args.extend(['--keep-go', str(root / 'go')])
                p = cli(*args, cwd=root)
                self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
                if target == 'py':
                    original = output.read_text()
                    modified = original.replace('HTTP_TOTAL_TIMEOUT = 30.0',
                                                'HTTP_TOTAL_TIMEOUT = 1.5')
                    self.assertNotEqual(original, modified)
                    output.write_text(modified)
                    command = [sys.executable, str(output)]
                else:
                    path = root / 'go/lm_prims_http.go'
                    original = path.read_text()
                    modified = re.sub(
                        r'httpTotalTimeout\s+= 30 \* time.Second',
                        'httpTotalTimeout = 1500 * time.Millisecond', original)
                    self.assertNotEqual(original, modified)
                    path.write_text(modified)
                    go_build(find_go(), root / 'go', output)
                    command = [str(output)]
            p = subprocess.run(command, cwd=root, env=environment(),
                               capture_output=True, timeout=30)
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
            self.assertEqual(p.stdout, expected, p.stderr)
            self.assertEqual(server.paths['/redirect-target'], 0)
            self.assertEqual(server.paths['/unused'], 0)
            self.assertEqual(server.paths['/drop'], 1)

    def test_interpreter_http_suite(self):
        self.differential('interp')

    def test_python_http_suite(self):
        self.differential('py')

    def test_go_http_suite(self):
        if find_go() is None:
            sys.stderr.write('\nSKIP: Go missing; HTTP differential NOT run\n')
            self.skipTest('Go toolchain not found')
        self.differential('go')
