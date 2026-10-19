"""System access contracts and identical interpreter, Go and Python behavior."""
import errno
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from lm.build import find_go
from lm.values import LmFail, show

ROOT = Path(__file__).resolve().parents[2]
EFFECTS = ('env.read', 'fs.read', 'fs.write', 'fs.delete', 'io.in', 'io.out')


def cli(*args, cwd=ROOT, env=None):
    return subprocess.run([sys.executable, '-m', 'lm', *args], cwd=cwd,
                          env=env, capture_output=True)


def environment():
    env = {**os.environ, 'PYTHONPATH': str(ROOT), 'LM_SYSTEM_EMPTY': '',
           'LM_SYSTEM_VALUE': 'héllo'}
    env.pop('LM_SYSTEM_UNSET', None)
    if os.name == 'posix':
        env['LM_SYSTEM_INVALID'] = os.fsdecode(b'a\xff\xe2\x82z\xed\xa0\x80')
    return env


def source(invalid_entries=True):
    """Generate one executable suite, shared unchanged by all three targets."""
    forms = []
    checks = []

    def path(name):
        return '(str.concat dir ' + show('/' + name) + ')'

    def check(expr):
        checks.append(expr)
        forms.append('(io.print (if ' + expr + ' "ok ' + str(len(checks))
                     + '" "BAD ' + str(len(checks)) + '"))')

    def call(fn, *args):
        forms.append('(fs.' + fn + ' ' + ' '.join(args) + ')')

    for name, expected in [('UNSET', 'None'), ('EMPTY', '(Some "")'),
                           ('VALUE', '(Some "héllo")')]:
        check('(= (env.lookup "LM_SYSTEM_' + name + '") ' + expected + ')')
    if os.name == 'posix':
        check('(= (env.lookup "LM_SYSTEM_INVALID") (Some "a��z���"))')
    for name in ['', '=', 'a=b', '\0']:
        check('(= (env.lookup ' + show(name) + ') None)')
    call('append', path('text'), '"é"')
    call('append', path('text'), '"tail"')
    check('(= (fs.read ' + path('text') + ') "étail")')
    call('append', path('text-link'), '"!"')
    check('(= (fs.read ' + path('text') + ') "étail!")')
    check('(= (fs.entries ' + path('sorted') + ') (list "A" "z" "é" "😀"))')
    check('(= (fs.entries ' + path('sorted-link') + ') (list "A" "z" "é" "😀"))')
    for name, expected in [('missing', 'false'), ('text', 'false'),
                           ('text/child', 'false'), ('sorted', 'true'),
                           ('sorted-link', 'true'), ('dangling', 'false')]:
        check('(= (fs.is-dir ' + path(name) + ') ' + expected + ')')
    call('make-dir', path('created'))
    check('(fs.is-dir ' + path('created') + ')')
    for name in ['created', 'text', 'dangling', 'missing/child']:
        check('(bad-make-dir ' + path(name) + ')')
    check('(bad-entries ' + path('text') + ')')
    if invalid_entries:
        check('(bad-entries ' + path('invalid-names') + ')')
    check('(bad-remove ' + path('sorted') + ')')
    call('remove', path('dangling'))
    call('remove', path('created'))
    check('(not (fs.exists ' + path('created') + '))')
    for old, new in [('text', 'occupied'), ('sorted', 'occupied-dir'),
                     ('text', 'dangling-target'), ('text', 'text'), ('sorted', 'sorted')]:
        check('(bad-rename ' + path(old) + ' ' + path(new) + ')')
    call('rename', path('text'), path('moved'))
    check('(and (not (fs.exists ' + path('text') + ')) (= (fs.read '
          + path('moved') + ') "étail!"))')
    call('rename', path('sorted'), path('moved-dir'))
    check('(and (not (fs.exists ' + path('sorted') + ')) (fs.is-dir '
          + path('moved-dir') + '))')
    call('rename', path('rename-link'), path('moved-link'))
    call('remove', path('moved'))
    check('(not (fs.exists ' + path('moved') + '))')
    for name in ['append', 'entries', 'is-dir', 'make-dir', 'remove']:
        check('(bad-' + name + ' "\\u{0}")')
    check('(bad-rename "\\u{0}" ' + path('unused') + ')')
    check('(bad-rename ' + path('occupied') + ' "\\u{0}")')
    wrappers = []
    for name, effect in [('append', 'fs.write'), ('entries', 'fs.read'),
                         ('is-dir', 'fs.read'), ('make-dir', 'fs.write'),
                         ('remove', 'fs.delete'), ('rename', 'fs.write fs.delete')]:
        sig = '(path Str)' + (' (to Str)' if name == 'rename' else '')
        args = 'path' + (' to' if name == 'rename' else ' "x"' if name == 'append' else '')
        result = '(fs.' + name + ' ' + args + ')'
        # Every wrapper returns false after success, regardless of the prim's type.
        body = '(let ((ignored ' + result + ')) false)'
        wrappers.append('(fn bad-' + name + ' (purpose "Catch the path contract.") '
                        '(sig ' + sig + ' -> Bool) (eff ' + effect + ') '
                        '(body (try ' + body + ' (catch fs.IoError (p msg) (= p path)))))')
    text = ('(module system-probe (purpose "Exercise system access in every target.") '
            '(use env fs io str) ' + ' '.join(wrappers)
            + ' (fn main (purpose "Run all system checks.") (sig -> Int) '
            '(eff ' + ' '.join(EFFECTS) + ') (fails fs.IoError) '
            '(body (match (io.args) ((cons dir _) (do ' + ' '.join(forms)
            + ' 0)) (_ 2)))))')
    expected = ''.join('ok ' + str(i) + '\n' for i in range(1, len(checks) + 1)).encode()
    return text, expected


class SystemAccess(unittest.TestCase):
    def test_host_errors_are_declared_failures(self):
        from lm.io_prims import fs_entries, fs_is_dir, fs_rename
        # macOS filesystems cannot create raw invalid UTF-8 names. Exercise the
        # surrogateescape representation returned by Unix listdir independently.
        with patch('lm.io_prims.os.listdir', return_value=['good', '\udcff']):
            with self.assertRaises(LmFail) as caught:
                fs_entries(None, 'directory')
        self.assertEqual((caught.exception.id, caught.exception.args_[0]),
                         ('fs.IoError', 'directory'))
        with patch('lm.io_prims.os.stat', side_effect=PermissionError(errno.EACCES, 'denied')):
            with self.assertRaises(LmFail) as caught:
                fs_is_dir(None, 'restricted')
        self.assertEqual((caught.exception.id, caught.exception.args_[0]),
                         ('fs.IoError', 'restricted'))
        with tempfile.TemporaryDirectory() as td:
            old, new = Path(td) / 'old', Path(td) / 'new'
            old.write_text('keep')
            with patch('lm.io_prims.os.link', side_effect=OSError(errno.EXDEV, 'cross-device')) as link:
                with self.assertRaises(LmFail) as caught:
                    fs_rename(None, str(old), str(new))
            link.assert_called_once_with(str(old), str(new))
            self.assertEqual((caught.exception.id, caught.exception.args_[0]),
                             ('fs.IoError', str(old)))
            self.assertEqual(old.read_text(), 'keep')
            self.assertFalse(new.exists())

    def test_lookup_values_and_invalid_names(self):
        cases = [('LM_SYSTEM_UNSET', 'None'), ('LM_SYSTEM_EMPTY', '(Some "")'),
                 ('LM_SYSTEM_VALUE', '(Some "héllo")'), ('', 'None'),
                 ('=', 'None'), ('x=y', 'None'), ('\0', 'None')]
        for name, expected in cases:
            with self.subTest(name=name):
                p = cli('run', 'env.lookup', show(name), '--allow', 'env.read', env=environment())
                self.assertEqual((p.returncode, p.stdout), (0, (expected + '\n').encode()), p.stderr)

    def test_denied_effects(self):
        for fn, args, allow in [('env.lookup', ['"LM_SYSTEM_VALUE"'], []),
                                ('fs.remove', ['"missing"'], []),
                                ('fs.rename', ['"a"', '"b"'], ['--allow', 'fs.write'])]:
            with self.subTest(fn=fn):
                p = cli('run', fn, *args, *allow)
                self.assertEqual(p.returncode, 1, p.stderr)
                self.assertEqual(json.loads(p.stderr)['code'], 'E-EFFECT-DENIED')
                self.assertEqual(p.stdout, b'')

    def test_scenario_effects_are_known(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / 'src').mkdir()
            (root / 'tests/accept').mkdir(parents=True)
            (root / 'src/demo.lm').write_text(
                '(module demo (purpose "Declare system effects.") '
                '(fn main (purpose "Return one.") (sig -> Int) '
                '(eff env.read fs.delete) (body 1)))')
            (root / 'tests/accept/demo.accept').write_text(
                '(scenarios (scenario "System effects" (status proposed) '
                '(why "Recognize both capabilities.") (allow env.read) '
                '(allow fs.delete) (run demo.main) (expect 1)))')
            p = cli('check', cwd=root, env=environment())
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)

    def differential(self, target):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / 'src').mkdir()
            src = root / 'src/system-probe.lm'
            data = root / 'data'
            data.mkdir()
            sorted_dir = data / 'sorted'
            sorted_dir.mkdir()
            for name in ['😀', 'é', 'z', 'A']:
                (sorted_dir / name).touch()
            (data / 'occupied').write_text('keep')
            (data / 'occupied-dir').mkdir()
            for link, dest in [('dangling', 'missing'), ('dangling-target', 'missing'),
                               ('rename-link', 'missing'), ('sorted-link', 'sorted'),
                               ('text-link', 'text')]:
                (data / link).symlink_to(dest)
            invalid_entries = False
            if os.name == 'posix':
                (data / 'invalid-names').mkdir()
                try:
                    fd = os.open(os.fsencode(data / 'invalid-names') + b'/\xff', os.O_CREAT | os.O_WRONLY, 0o600)
                except OSError as ex:
                    if ex.errno not in (errno.EPERM, errno.EINVAL, errno.EILSEQ):
                        raise
                    sys.stderr.write('\nSKIP: host cannot create invalid UTF-8 names: ' + str(ex) + '\n')
                else:
                    os.close(fd)
                    invalid_entries = True
            text, expected = source(invalid_entries)
            src.write_text(text)
            p = cli('edit', 'apply', json.dumps({'op': 'fmt', 'file': str(src)}),
                    cwd=root, env=environment())
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
            if target == 'interp':
                args = ['run', 'system-probe.main']
                for effect in EFFECTS:
                    args.extend(['--allow', effect])
                p = cli(*args, '--', str(data), cwd=root, env=environment())
                # lm run prints its return value after program output.
                expected += b'0\n'
            else:
                output = root / ('probe.py' if target == 'py' else 'probe')
                p = cli('build', '--target', target, 'system-probe.main', str(src), '-o', str(output))
                self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
                command = [sys.executable, str(output)] if target == 'py' else [str(output)]
                p = subprocess.run([*command, str(data)], capture_output=True, env=environment())
            self.assertEqual(p.returncode, 0, p.stderr)
            self.assertEqual(p.stdout, expected, p.stderr)
            self.assertFalse(os.path.lexists(data / 'dangling'))
            self.assertFalse(os.path.lexists(data / 'rename-link'))
            self.assertTrue((data / 'moved-link').is_symlink())
            self.assertEqual(os.readlink(data / 'moved-link'), 'missing')
            self.assertEqual((data / 'occupied').read_text(), 'keep')

    def test_interpreter_system_suite(self):
        self.differential('interp')

    def test_python_system_suite(self):
        self.differential('py')

    def test_go_system_suite(self):
        if find_go() is None:
            sys.stderr.write('\nSKIP: Go toolchain not found; system differential NOT run\n')
            self.skipTest('Go toolchain not found')
        self.differential('go')
