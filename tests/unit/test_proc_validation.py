"""Subprocess validation boundaries, pipe failures and descriptor isolation."""
import errno
import os
import subprocess
import sys
import unittest
from unittest.mock import Mock, patch

from lm import proc_prims as proc
from lm.values import LmFail, Pair, Var


NONE = Var('', 'None')


class NoEncode(str):
    def encode(self, *args, **kwargs):
        raise AssertionError('later validation step was reached')


class NoTruth(str):
    def __bool__(self):
        raise AssertionError('environment name validation was reached')


class ProcValidation(unittest.TestCase):
    def invalid(self, argv=('/x',), stdin='', cwd=NONE, env=()):
        with self.assertRaises(LmFail) as caught:
            proc.validate_request(argv, stdin, cwd, env)
        self.assertEqual(caught.exception.id, 'proc.ProcError')
        self.assertEqual(caught.exception.args_, ('invalid-request',))

    def test_validation_order_stops_before_later_steps(self):
        # Empty argv and then relative executable precede even inspecting cwd.
        self.invalid(argv=(), cwd=object())
        self.invalid(argv=('relative',), cwd=object())
        # NUL precedes name validity; invalid and duplicate names precede size.
        self.invalid(stdin='\0', env=(Pair(NoTruth(''), ''),))
        self.invalid(stdin=NoEncode(''), env=(Pair('', ''),))
        self.invalid(stdin=NoEncode(''),
                     env=(Pair('K', 'one'), Pair('K', 'two')))
        # Stdin size precedes encoding argv for the request size.
        with patch.object(proc, 'PROC_STDIN_LIMIT', 1):
            self.invalid(argv=(NoEncode('/x'),), stdin='é')

    def test_input_limit_counts_utf8_and_accepts_the_boundary(self):
        with patch.object(proc, 'PROC_STDIN_LIMIT', 8):
            raw, directory, env = proc.validate_request(
                ('/x',), 'é' * 4, NONE, ())
            self.assertEqual(raw, b'\xc3\xa9' * 4)
            self.assertIsNone(directory)
            self.assertEqual(env, {})
            self.invalid(stdin='é' * 4 + 'a')

    def test_request_limit_counts_encoded_env_equals_without_terminators(self):
        # /x = 2, é = 2, K=é = 4 bytes: exactly 8 total.
        env = (Pair('K', 'é'),)
        with patch.object(proc, 'PROC_REQUEST_LIMIT', 8):
            result = proc.validate_request(
                ('/x', 'é'), '', Var('', 'Some', ('a-relative-cwd',)), env)
            self.assertEqual(result, (b'', 'a-relative-cwd', {'K': 'é'}))
            self.invalid(argv=('/x', 'éa'), env=env)
            self.invalid(argv=('/x', 'é'), env=(Pair('K', 'éa'),))

    def test_invalid_requests_never_spawn_even_on_unsupported_hosts(self):
        with patch.object(proc.os, 'name', 'nt'), \
                patch.object(proc.subprocess, 'Popen') as spawn:
            with self.assertRaises(LmFail) as caught:
                proc.proc_run(None, (), '', NONE, ())
        self.assertEqual(caught.exception.args_, ('invalid-request',))
        spawn.assert_not_called()

    def test_pipe_allocation_and_start_error_categories(self):
        cases = ((errno.EMFILE, 'spawn'), (errno.ENFILE, 'spawn'),
                 (errno.ENOEXEC, 'spawn'), (errno.E2BIG, 'spawn'),
                 (errno.ENOENT, 'not-found'), (errno.ENOTDIR, 'not-found'),
                 (errno.EACCES, 'permission'), (errno.EPERM, 'permission'))
        for number, expected in cases:
            with self.subTest(errno=number), patch.object(
                    proc.subprocess, 'Popen',
                    side_effect=OSError(number, 'private host text')):
                with self.assertRaises(LmFail) as caught:
                    proc.proc_run(None, ('/private/argv',), '', NONE, ())
                self.assertEqual(caught.exception.args_, (expected,))

    def test_pipe_allocation_error_closes_created_fds_without_spawning(self):
        reader, writer = os.pipe()
        with patch.object(proc.os, 'pipe', side_effect=[
                (reader, writer), OSError(errno.EMFILE, 'host secret')]), \
                patch.object(proc.subprocess, 'Popen') as spawn:
            with self.assertRaises(LmFail) as caught:
                proc.proc_run(None, ('/bin/sh',), '', NONE, ())
        self.assertEqual(caught.exception.args_, ('io',))
        spawn.assert_not_called()
        for fd in (reader, writer):
            with self.assertRaises(OSError):
                os.fstat(fd)

    def test_start_failure_closes_all_allocated_pipe_descriptors(self):
        descriptors = []
        real_pipe = proc.os.pipe

        def pipe():
            fds = real_pipe()
            descriptors.extend(fds)
            return fds

        with patch.object(proc.os, 'pipe', side_effect=pipe), \
                patch.object(proc.subprocess, 'Popen',
                             side_effect=OSError(errno.EMFILE, 'host secret')):
            with self.assertRaises(LmFail) as caught:
                proc.proc_run(None, ('/bin/sh',), '', NONE, ())
        self.assertEqual(caught.exception.args_, ('spawn',))
        self.assertEqual(len(descriptors), 6)
        for fd in descriptors:
            with self.assertRaises(OSError):
                os.fstat(fd)

    def test_cleanup_denial_for_exited_leader_preserves_original_failure(self):
        child = Mock(pid=123)
        child.poll.return_value = 0
        with patch.object(proc.os, 'killpg', side_effect=PermissionError):
            proc._kill_group(child)
        self.assertEqual(child.wait.call_args_list[0].kwargs, {'timeout': 0.1})

    def test_cleanup_denial_for_live_leader_kills_reaps_and_fails_io(self):
        child = Mock(pid=123)
        child.poll.return_value = None
        child.wait.side_effect = [
            proc.subprocess.TimeoutExpired('child', 0.1), None]
        with patch.object(proc.os, 'killpg', side_effect=PermissionError):
            with self.assertRaises(LmFail) as caught:
                proc._kill_group(child)
        self.assertEqual(caught.exception.args_, ('io',))
        child.kill.assert_called_once_with()
        self.assertEqual(child.wait.call_count, 2)


@unittest.skipUnless(os.name == 'posix', 'POSIX subprocess pipe isolation')
class ProcPipeFailures(unittest.TestCase):
    def test_child_environment_uses_utf8_with_ascii_host_fsencoding(self):
        def ascii_fsencode(value):
            return value.encode('ascii') if isinstance(value, str) else value

        with patch.object(proc.os, 'fsencode', side_effect=ascii_fsencode):
            result = proc.proc_run(
                None, ('/bin/sh', '-c', 'printf "%s" "$TAG"'), '', NONE,
                (Pair('TAG', 'é'),))
        self.assertEqual(dict(result.items)['stdout'], 'é')

    def test_utf8_arguments_and_env_ignore_the_parent_locale(self):
        driver = (
            'import json; from lm.proc_prims import proc_run; '
            'from lm.values import Pair,Var; '
            'r=proc_run(None,("/bin/sh","-c",'
            '\'printf "%s" "$1:$TAG"\',"marker","h\\u00e9llo"),'
            '\'\',Var("","None"),(Pair("TAG","\\u00e9"),)); '
            'print(json.dumps(dict(r.items)["stdout"]))')
        env = {**os.environ, 'LC_ALL': 'C', 'PYTHONUTF8': '0',
               'PYTHONCOERCECLOCALE': '0'}
        result = subprocess.run([sys.executable, '-c', driver], env=env,
                                capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, b'"h\\u00e9llo:\\u00e9"\n')

    def test_combined_output_limit_accepts_exact_utf8_byte_boundary(self):
        with patch.object(proc, 'PROC_OUTPUT_LIMIT', 8):
            result = proc.proc_run(
                None, ('/bin/sh', '-c', 'printf éé; printf éé >&2'),
                '', NONE, ())
            self.assertEqual(dict(result.items)['stdout'], 'éé')
            self.assertEqual(dict(result.items)['stderr'], 'éé')
            with self.assertRaises(LmFail) as caught:
                proc.proc_run(
                    None, ('/bin/sh', '-c', 'printf éé; printf ééx >&2'),
                    '', NONE, ())
            self.assertEqual(caught.exception.args_, ('limit',))

    def test_pipe_wrapping_error_closes_fds_kills_and_reaps(self):
        children, descriptors, streams = [], [], []
        real_spawn, real_pipe = proc.subprocess.Popen, proc.os.pipe
        real_fdopen = proc.os.fdopen

        def spawn(*args, **kwargs):
            child = real_spawn(*args, **kwargs)
            children.append(child)
            return child

        def pipe():
            fds = real_pipe()
            descriptors.extend(fds)
            return fds

        def fdopen(*args, **kwargs):
            if streams:
                raise OSError(errno.EIO, 'host secret')
            stream = real_fdopen(*args, **kwargs)
            streams.append(stream)
            return stream

        with patch.object(proc.os, 'pipe', side_effect=pipe), \
                patch.object(proc.os, 'fdopen', side_effect=fdopen), \
                patch.object(proc.subprocess, 'Popen', side_effect=spawn):
            with self.assertRaises(LmFail) as caught:
                proc.proc_run(None, ('/bin/sh', '-c', '/bin/sleep 10'),
                              '', NONE, ())
        self.assertEqual(caught.exception.args_, ('io',))
        self.assertIsNotNone(children[0].returncode)
        self.assertTrue(streams[0].closed)
        for fd in descriptors:
            with self.assertRaises(OSError):
                os.fstat(fd)

    def call_and_capture(self, script, stdin=''):
        children = []
        original = proc.subprocess.Popen

        def spawn(*args, **kwargs):
            child = original(*args, **kwargs)
            children.append(child)
            return child

        with patch.object(proc.subprocess, 'Popen', side_effect=spawn):
            with patch.object(proc, 'PROC_TOTAL_TIMEOUT', 2):
                result = proc.proc_run(None, ('/bin/sh', '-c', script),
                                       stdin, NONE, ())
        return result, children

    def test_broken_stdin_pipe_closes_and_outputs_are_drained(self):
        original_kill = proc.os.killpg
        with patch.object(proc.os, 'killpg', wraps=original_kill) as kill:
            result, children = self.call_and_capture(
                'exec 0<&-; /bin/sleep 0.1; printf done; printf err >&2',
                'x' * 2000000)
        self.assertEqual(dict(result.items), {
            'exit': Var('proc', 'Exited', (0,)),
            'stdout': 'done', 'stderr': 'err'})
        kill.assert_not_called()
        self.assertEqual(children[0].returncode, 0)
        for stream in (children[0].stdin, children[0].stdout,
                       children[0].stderr):
            self.assertTrue(stream.closed)

    def test_read_and_write_pipe_errors_are_fixed_category_and_reap(self):
        original = proc._communicate
        for operation in ('read', 'write'):
            children = []
            real_spawn = proc.subprocess.Popen

            def spawn(*args, **kwargs):
                child = real_spawn(*args, **kwargs)
                children.append(child)
                return child

            def communicate(*args):
                error = OSError(errno.EIO, 'host secret')
                with patch.object(proc.os, operation, side_effect=error):
                    return original(*args)

            spawn_patch = patch.object(proc.subprocess, 'Popen',
                                       side_effect=spawn)
            with self.subTest(operation=operation), spawn_patch, \
                    patch.object(proc, '_communicate', communicate):
                with self.assertRaises(LmFail) as caught:
                    proc.proc_run(None, ('/bin/sh', '-c',
                                        'printf ready; /bin/sleep 1'),
                                  'x' * 1048577, NONE, ())
                self.assertEqual(caught.exception.args_, ('io',))
                self.assertIsNotNone(children[0].returncode)
                for stream in (children[0].stdin, children[0].stdout,
                               children[0].stderr):
                    self.assertTrue(stream.closed)

    def test_explicitly_inheritable_unrelated_descriptor_is_closed(self):
        import fcntl
        reader, writer = os.pipe()
        descriptor = fcntl.fcntl(reader, fcntl.F_DUPFD, 128)
        os.set_inheritable(descriptor, True)
        try:
            script = (f'if test -e /dev/fd/{descriptor}; '
                      'then printf inherited; else printf closed; fi')
            result = proc.proc_run(None, ('/bin/sh', '-c', script),
                                   '', NONE, ())
            self.assertEqual(dict(result.items)['stdout'], 'closed')
        finally:
            os.close(descriptor)
            os.close(reader)
            os.close(writer)
