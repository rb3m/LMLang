"""Pinned third-party closure and offline fetch fixtures (ADR-078)."""
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from lm.check import Checker
from lm.cli import main
from lm.loader import load
from lm.printer import format_text

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / 'tests/spec/deps'
SOURCE = b'''(module geo
  (purpose "External dependency.")
  (fn value
    (purpose "Return seven.")
    (sig -> Int)
    (body 7)))
'''
MAIN = '''(module main
  (purpose "Pinned dependency program.")
  (use geo)
  (fn main
    (purpose "Call dependency.")
    (sig -> Int)
    (example () => 7)
    (body (geo.value))))
'''


class DependencyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='lm-deps-')
        self.addCleanup(self.tmp.cleanup)
        self.project = Path(self.tmp.name)
        self.cache = self.project / '.cache'
        self.old_cwd = Path.cwd()
        os.chdir(self.project)
        self.addCleanup(os.chdir, self.old_cwd)
        env = patch.dict(os.environ, {'LM_CACHE': str(self.cache)})
        env.start()
        self.addCleanup(env.stop)
        Path('src').mkdir()
        self.write_main()

    def write_main(self):
        canonical, diags = format_text(MAIN, 'src/main.lm')
        self.assertFalse(diags)
        Path('src/main.lm').write_text(canonical, encoding='utf-8')

    def pin(self, source=SOURCE, stem='geo', cached=True, allow=None):
        digest = hashlib.sha256(source).hexdigest()
        Path('lm.deps').write_text(
            f'(deps\n  (pin {stem} "https://example.org/{stem}.lm" "{digest}"'
            + (f' (allow {allow})' if allow is not None else '') + '))\n')
        path = self.cache / digest / f'{stem}.lm'
        if cached:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(source)
        return path

    def check(self):
        prog = load(['src'])
        Checker(prog).run()
        return prog

    def cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(list(args))
        return code, out.getvalue(), err.getvalue()

    def test_spec_fixtures(self):
        for fixture in sorted(FIXTURES.iterdir()):
            with self.subTest(fixture=fixture.name):
                shutil.rmtree('src')
                shutil.rmtree(self.cache, ignore_errors=True)
                shutil.copytree(fixture / 'src', 'src')
                shutil.copyfile(fixture / 'lm.deps', 'lm.deps')
                if (fixture / 'cached.txt').exists():
                    match = re.search(r'\(pin ([a-z-]+) "[^"]+" "([a-f0-9]{64})"', Path('lm.deps').read_text())
                    if match:
                        path = self.cache / match[2] / (match[1] + '.lm')
                        path.parent.mkdir(parents=True)
                        path.write_bytes((fixture / 'cached.txt').read_bytes())
                prog = self.check()
                want = set((fixture / 'expect').read_text().split())
                got = {d.code for d in prog.diags if d.severity == 'error'}
                self.assertEqual(want, got)
                for diag in prog.diags:
                    if diag.code in {'E-DEP-UNFETCHED', 'E-DEP-HASH', 'E-DEPS'}:
                        self.assertEqual(Path(diag.file).name, 'lm.deps')
                        self.assertGreaterEqual(diag.line, 1)
                        self.assertGreaterEqual(diag.col, 1)
                    if diag.code in {'E-DEP-UNFETCHED', 'E-DEP-HASH'}:
                        self.assertEqual(diag.line, 2)
                        self.assertEqual(diag.fix, [{'op': 'fetch'}])
                    if diag.code == 'E-DEP-UNPINNED':
                        self.assertEqual(Path(diag.file).name, 'geo.lm')
                        self.assertEqual(diag.line, 3)

    def test_valid_pin_loads_and_tests(self):
        self.pin()
        prog = self.check()
        self.assertFalse([d.to_json() for d in prog.diags if d.severity == 'error'])
        self.assertFalse(prog.modules['geo'].is_target)
        self.assertFalse(prog.modules['geo'].is_stdlib)
        self.assertEqual(prog.targets, ['main'])
        code, out, err = self.cli('test')
        self.assertEqual(code, 0, out + err)
        code, out, err = self.cli('run', 'main.main')
        self.assertEqual((code, out.strip()), (0, '7'), err)

    def test_bad_manifests(self):
        good = '"https://example.org/geo.lm" "' + 'a' * 64 + '"'
        cases = ['(', '(module geo)', f'(deps (pin Bad {good}))',
                 f'(deps (pin geo "http://example.org/a" "{"a" * 64}"))',
                 '(deps (pin geo "https://example.org/a" "ABC"))',
                 f'(deps (pin geo {good}) (pin geo {good}))']
        for text in cases:
            with self.subTest(text=text):
                Path('lm.deps').write_text(text)
                self.assertIn('E-DEPS', {d.code for d in self.check().diags})

    def test_fetch_success_and_cache_hit(self):
        path = self.pin(cached=False)
        with patch('lm.deps.download', return_value=SOURCE) as download:
            code, out, err = self.cli('fetch')
            self.assertEqual(code, 0, out + err)
            self.assertEqual(json.loads(out)['status'], 'fetched')
            self.assertEqual(path.read_bytes(), SOURCE)
            code, out, err = self.cli('fetch')
            self.assertEqual(code, 0, out + err)
            self.assertEqual(json.loads(out)['status'], 'cached')
            download.assert_called_once_with('https://example.org/geo.lm')

    def test_fetch_mismatch_writes_nothing(self):
        path = self.pin(cached=False)
        with patch('lm.deps.download', return_value=SOURCE + b'\n'):
            code, out, err = self.cli('fetch')
        self.assertEqual(code, 1, out + err)
        self.assertEqual(json.loads(out)['status'], 'error')
        self.assertFalse(path.exists())
        self.assertFalse(list(self.cache.rglob('*')) if self.cache.exists() else [])

    def test_fetch_non_https_refused_before_download(self):
        with patch('lm.deps.download', return_value=SOURCE) as download:
            code, out, err = self.cli('fetch', '--pin', 'geo', 'http://example.org/geo.lm')
        self.assertNotEqual(code, 0, out + err)
        download.assert_not_called()
        self.assertFalse(Path('lm.deps').exists())

    def test_pin_writes_sorted_canonical_manifest_and_replaces(self):
        digest = hashlib.sha256(SOURCE).hexdigest()
        with patch('lm.deps.download', return_value=SOURCE):
            for stem in ('zebra', 'alpha', 'zebra'):
                code, out, err = self.cli('fetch', '--pin', stem, f'https://example.org/{stem}.lm')
                self.assertEqual(code, 0, out + err)
                self.assertIn(f'(pin {stem} "https://example.org/{stem}.lm" "{digest}")', out)
        expected = '(deps\n' + ''.join(
            f'  (pin {s} "https://example.org/{s}.lm" "{digest}")' + ('\n' if s == 'alpha' else ')\n')
            for s in ('alpha', 'zebra'))
        self.assertEqual(Path('lm.deps').read_text(), expected)
        for stem in ('alpha', 'zebra'):
            self.assertEqual((self.cache / digest / f'{stem}.lm').read_bytes(), SOURCE)

    def test_python_build_and_run(self):
        self.pin()
        script = self.project / 'program.py'
        code, out, err = self.cli('build', '--target', 'py', 'main.main', '-o', str(script))
        self.assertEqual(code, 0, out + err)
        proc = subprocess.run([sys.executable, str(script)], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 7, proc.stdout + proc.stderr)

    def test_fetch_hashes_exact_bytes_without_parsing(self):
        for source in (SOURCE.replace(b'\n', b'\r\n'), b'not LM at all: \xff\x00'):
            with self.subTest(source=source):
                with patch('lm.deps.download', return_value=source):
                    code, out, err = self.cli('fetch', '--pin', 'geo', 'https://example.org/geo.lm')
                self.assertEqual(code, 0, out + err)
                digest = hashlib.sha256(source).hexdigest()
                self.assertIn(digest, Path('lm.deps').read_text())
                self.assertEqual((self.cache / digest / 'geo.lm').read_bytes(), source)

    def test_loader_hashes_raw_bytes_and_never_downloads(self):
        self.pin(SOURCE.replace(b'\n', b'\r\n'))
        with patch('lm.deps.download', side_effect=AssertionError('loader must remain offline')):
            prog = self.check()
        self.assertEqual([d.code for d in prog.diags if d.severity == 'error'], [])

    def test_fetch_error_continues_remaining_pins(self):
        digest = hashlib.sha256(SOURCE).hexdigest()
        Path('lm.deps').write_text('(deps\n' + '\n'.join(
            f'  (pin {stem} "https://example.org/{stem}.lm" "{digest}")'
            for stem in ('alpha', 'zebra')) + ')\n')
        with patch('lm.deps.download', side_effect=[ValueError('network failure'), SOURCE]):
            code, out, err = self.cli('fetch')
        self.assertEqual(code, 1, out + err)
        self.assertEqual([(r['stem'], r['status']) for r in map(json.loads, out.splitlines())],
                         [('alpha', 'error'), ('zebra', 'fetched')])
        self.assertFalse((self.cache / digest / 'alpha.lm').exists())
        self.assertEqual((self.cache / digest / 'zebra.lm').read_bytes(), SOURCE)

    def test_fetch_repairs_corrupt_cache(self):
        path = self.pin()
        path.write_bytes(b'corrupt')
        with patch('lm.deps.download', return_value=SOURCE):
            code, out, err = self.cli('fetch')
        self.assertEqual(code, 0, out + err)
        self.assertEqual(path.read_bytes(), SOURCE)

    def test_external_cannot_use_another_pin(self):
        source = SOURCE.replace(b'  (fn value', b'  (use helper)\n  (fn value').replace(
            b'(body 7)', b'(body (helper.value))')
        helper = SOURCE.replace(b'module geo', b'module helper').replace(
            b'  (fn value', b'  (use math)\n  (fn value').replace(b'(body 7)', b'(body (math.max 6 7))')
        self.pin(source)
        manifest = Path('lm.deps').read_text().rstrip()[:-1]
        digest = hashlib.sha256(helper).hexdigest()
        Path('lm.deps').write_text(manifest + f'\n  (pin helper "https://example.org/helper.lm" "{digest}"))\n')
        path = self.cache / digest / 'helper.lm'
        path.parent.mkdir(parents=True)
        path.write_bytes(helper)
        code, out, err = self.cli('test')
        self.assertEqual(code, 1, out + err)
        diag = next(d for d in self.check().diags if d.code == 'E-DEP-UNPINNED')
        self.assertEqual(diag.line, 3)
        self.assertEqual(Path(diag.file).name, 'geo.lm')

    def test_declared_effect_allowance(self):
        source = SOURCE.replace(b'  (fn value', b'  (use io)\n  (fn value').replace(
            b'    (body 7)', b'    (eff io.out)\n    (body (do (io.print "hello") 7))')
        canonical, _ = format_text(MAIN.replace('(geo.value)', '7'), 'src/main.lm')
        Path('src/main.lm').write_text(canonical)
        self.pin(source)
        diag = next(d for d in self.check().diags if d.code == 'E-DEP-EFFECT')
        self.assertEqual((diag.file, diag.line), ('lm.deps', 2))
        self.assertIn('geo.value', diag.msg)
        self.assertIn('io.out', diag.msg)
        self.pin(source, allow='io.out')
        self.assertFalse([d.to_json() for d in self.check().diags if d.severity == 'error'])
        self.pin(source.replace(b'    (eff io.out)\n', b''), allow='io.out')
        diag = next(d for d in self.check().diags if d.code == 'E-EFFECT-UNDECLARED')
        self.assertIs(json.loads(diag.to_json())['ext'], True)

    def test_forbidden_allowances_even_without_function_effects(self):
        for allow in ('proc.run', 'fs.read net.http', 'env.read net.http'):
            with self.subTest(allow=allow):
                self.pin(allow=allow)
                diag = next(d for d in self.check().diags if d.code == 'E-DEP-EFFECT')
                self.assertEqual((diag.file, diag.line), ('lm.deps', 2))
                self.assertIn(allow.split()[0], diag.msg)

    def test_malformed_allowances(self):
        for clause in ('(allow mystery)', '(allow io.out io.out)',
                       '(allow io.out io.in)', '(allow "io.out")',
                       '(nope io.out)', 'io.out', '(allow (io.out))',
                       '(allow io.out) (allow io.in)'):
            with self.subTest(clause=clause):
                self.pin()
                p = Path('lm.deps')
                p.write_text(p.read_text().rstrip()[:-2] + ' ' + clause + '))\n')
                self.assertIn('E-DEPS', {d.code for d in self.check().diags})

    def test_unused_nonstdlib_use_and_external_diagnostics(self):
        path = self.pin(SOURCE.replace(b'  (fn value', b'  (use unknown)\n  (fn value'))
        diag = next(d for d in self.check().diags if d.code == 'E-DEP-UNPINNED')
        self.assertEqual((diag.file, diag.line), (str(path), 3))
        self.assertIs(json.loads(diag.to_json())['ext'], True)
        self.pin(b'(module geo')
        diag = next(d for d in self.check().diags if d.code == 'E-PARSE')
        self.assertIs(json.loads(diag.to_json())['ext'], True)

    def test_external_examples_are_not_run(self):
        self.pin(SOURCE.replace(b'    (body 7)', b'    (example () => 999)\n    (body 7)'))
        code, out, err = self.cli('test')
        self.assertEqual(code, 0, out + err)
        from lm.runner import test_program
        diags, stats = test_program(self.check())
        self.assertFalse(diags)
        self.assertEqual(stats['examples'], 1)

    def test_index_and_slice_mark_external_symbols(self):
        self.pin()
        code, out, err = self.cli('index')
        self.assertEqual(code, 0, out + err)
        self.assertIn('ext module geo', out)
        self.assertRegex(out, r'(?m)^ext [ *]fn geo.value')
        for symbol in ('geo.value', 'main.main'):
            code, out, err = self.cli('slice', symbol)
            self.assertEqual(code, 0, out + err)
            self.assertIn('ext (module geo', out)
            self.assertIn('ext   (fn value', out)

    def test_fetch_allow_canonical_and_preserves_other_allowances(self):
        self.pin(allow='time.now')
        with patch('lm.deps.download', return_value=SOURCE):
            code, out, err = self.cli('fetch', '--pin', 'alpha',
                                      'https://example.org/alpha.lm',
                                      '--allow', 'io.out', '--allow', 'io.in')
        self.assertEqual(code, 0, out + err)
        self.assertIn('(allow io.in io.out)', out)
        manifest = Path('lm.deps').read_text()
        self.assertIn('(allow io.in io.out)', manifest)
        self.assertIn('(allow time.now)', manifest)
        self.assertLess(manifest.index('(pin alpha'), manifest.index('(pin geo'))
        self.pin(allow='')
        with patch('lm.deps.download', return_value=SOURCE):
            code, out, err = self.cli('fetch', '--pin', 'alpha', 'https://example.org/alpha.lm')
        self.assertEqual(code, 0, out + err)
        self.assertIn('(allow)', Path('lm.deps').read_text())

    def test_loader_parses_the_verified_read_once(self):
        path = self.pin()
        read_bytes, read_text = Path.read_bytes, Path.read_text
        reads = []
        def bytes_once(p):
            if p == path:
                reads.append(p)
                return SOURCE if len(reads) == 1 else b'changed'
            return read_bytes(p)
        def no_reread(p, *args, **kwargs):
            if p == path:
                self.fail('verified cache bytes must not be read again as text')
            return read_text(p, *args, **kwargs)
        with patch.object(Path, 'read_bytes', bytes_once), patch.object(Path, 'read_text', no_reread):
            prog = self.check()
        self.assertEqual(reads, [path])
        self.assertFalse([d.to_json() for d in prog.diags if d.severity == 'error'])
        self.assertEqual(prog.modules['geo'].text, SOURCE.decode())

    def test_go_build_and_run(self):
        from lm.build import find_go
        if find_go() is None:
            sys.stderr.write('SKIP: Go dependency build (go unavailable)\n')
            self.skipTest('go unavailable')
        self.pin()
        binary = self.project / 'program'
        code, out, err = self.cli('build', '--target', 'go', 'main.main', '-o', str(binary))
        self.assertEqual(code, 0, out + err)
        proc = subprocess.run([str(binary)], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 7, proc.stdout + proc.stderr)


class DependencyTransportTests(unittest.TestCase):
    def download(self, response):
        from lm import deps_http
        socket = Mock()
        tls = Mock()
        tls.wrap_socket.return_value = socket
        with patch.object(deps_http.http, '_connect', return_value=socket) as connect, \
                patch.object(deps_http.http, '_system_tls', return_value=tls), \
                patch.object(deps_http.http, '_Response', return_value=response):
            data = deps_http.download_bytes('https://example.org/module.lm')
        connect.assert_called_once()
        tls.wrap_socket.assert_called_once_with(socket, server_hostname='example.org')
        socket.close.assert_called_once()
        return data

    def response(self, status=200, length=3, chunks=(b'abc', b'')):
        response = Mock(status=status, length=length)
        response.read.side_effect = chunks
        return response

    def test_raw_bytes_and_verified_tls(self):
        response = self.response(chunks=(b'\xff\x00\r', b''))
        self.assertEqual(self.download(response), b'\xff\x00\r')
        response.close.assert_called_once()

    def test_non_200_and_redirect_refused(self):
        for status in (301, 302, 307, 404, 500):
            with self.subTest(status=status):
                response = self.response(status=status)
                with self.assertRaisesRegex(ValueError, 'HTTP status'):
                    self.download(response)
                response.read.assert_not_called()
                response.close.assert_called_once()

    def test_size_limit_for_known_and_streamed_body(self):
        from lm.http_prims import HTTP_BODY_LIMIT
        for length, chunks in ((HTTP_BODY_LIMIT + 1, ()),
                               (None, (b'x' * (HTTP_BODY_LIMIT + 1),))):
            with self.subTest(length=length):
                response = self.response(length=length, chunks=chunks)
                with self.assertRaisesRegex(ValueError, '8 MiB'):
                    self.download(response)
                response.close.assert_called_once()

    def test_truncated_body_refused(self):
        with self.assertRaisesRegex(ValueError, 'incomplete'):
            self.download(self.response(length=4))


if __name__ == '__main__':
    unittest.main()
