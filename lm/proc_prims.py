"""Bounded POSIX subprocesses shared by the interpreter and Python target."""
from __future__ import annotations

import errno
import os
import selectors
import signal
import subprocess
import time

from .values import LmFail, Rec, Var

PROC_TOTAL_TIMEOUT = 30.0
PROC_STDIN_LIMIT = 8 * 1024 * 1024
PROC_OUTPUT_LIMIT = 8 * 1024 * 1024
PROC_REQUEST_LIMIT = 64 * 1024


def _fail(category):
    raise LmFail('proc.ProcError', (category,)) from None


def validate_request(argv, stdin, cwd, env):
    """Validate in language-defined order, without observing the host."""
    if not argv:
        _fail('invalid-request')
    if not argv[0].startswith('/'):
        _fail('invalid-request')
    directory = cwd.args[0] if cwd.name == 'Some' else None
    strings = list(argv) + [stdin]
    if directory is not None:
        strings.append(directory)
    strings.extend(s for entry in env for s in (entry.a, entry.b))
    if any('\0' in s for s in strings):
        _fail('invalid-request')
    if any(not entry.a or '=' in entry.a for entry in env):
        _fail('invalid-request')
    names = [entry.a for entry in env]
    if len(set(names)) != len(names):
        _fail('invalid-request')
    try:
        raw_stdin = stdin.encode('utf-8')
        if len(raw_stdin) > PROC_STDIN_LIMIT:
            _fail('invalid-request')
        request_size = sum(len(s.encode('utf-8')) for s in argv)
        request_size += sum(len((entry.a + '=' + entry.b).encode('utf-8'))
                            for entry in env)
    except UnicodeError:
        _fail('invalid-request')
    if request_size > PROC_REQUEST_LIMIT:
        _fail('invalid-request')
    return raw_stdin, directory, {entry.a: entry.b for entry in env}


def _kill_group(child):
    try:
        os.killpg(child.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    except PermissionError:
        # Some restricted POSIX hosts deny signals to an extinct group. Keep
        # the original failure only after reaping its already-exiting leader.
        try:
            child.wait(timeout=0.1)
        except subprocess.TimeoutExpired:
            try:
                child.kill()
                child.wait()
            except OSError:
                pass
            _fail('io')
    child.wait()


def _remaining(deadline):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        _fail('timeout')
    return remaining


def _communicate(child, raw_stdin, deadline):
    """Multiplex all three pipes; bound memory before appending a read."""
    outputs = {'stdout': bytearray(), 'stderr': bytearray()}
    sent, received = 0, 0
    with selectors.DefaultSelector() as selector:
        for stream, kind in ((child.stdout, 'stdout'),
                             (child.stderr, 'stderr')):
            os.set_blocking(stream.fileno(), False)
            selector.register(stream, selectors.EVENT_READ, kind)
        if raw_stdin:
            os.set_blocking(child.stdin.fileno(), False)
            selector.register(child.stdin, selectors.EVENT_WRITE, 'stdin')
        else:
            child.stdin.close()
        while selector.get_map():
            events = selector.select(_remaining(deadline))
            for key, _ in events:
                stream, kind = key.fileobj, key.data
                if kind == 'stdin':
                    try:
                        sent += os.write(
                            stream.fileno(), raw_stdin[sent:sent + 65536])
                    except BlockingIOError:
                        continue
                    except OSError as error:
                        if error.errno != errno.EPIPE:
                            raise
                        selector.unregister(stream)
                        stream.close()
                        continue
                    if sent == len(raw_stdin):
                        selector.unregister(stream)
                        stream.close()
                    continue
                try:
                    chunk = os.read(stream.fileno(), min(
                        65536, PROC_OUTPUT_LIMIT + 1 - received))
                except BlockingIOError:
                    continue
                if not chunk:
                    selector.unregister(stream)
                    stream.close()
                    continue
                received += len(chunk)
                if received > PROC_OUTPUT_LIMIT:
                    _fail('limit')
                outputs[kind].extend(chunk)
        try:
            child.wait(timeout=_remaining(deadline))
        except subprocess.TimeoutExpired:
            _fail('timeout')
    return outputs


def _close_streams(child):
    failed = False
    for stream in (child.stdin, child.stdout, child.stderr):
        if stream is not None:
            try:
                stream.close()
            except OSError:
                failed = True
    if failed:
        _fail('io')


def _spawn(argv, directory, environment):
    """Distinguish pipe allocation failures from process start failures."""
    owned, pipes = set(), []
    child = None
    # POSIX accepts bytes; avoid the parent locale's filesystem encoding.
    arguments = tuple(s.encode('utf-8') for s in argv)
    child_env = {k.encode('utf-8'): v.encode('utf-8')
                 for k, v in environment.items()}
    child_dir = directory.encode('utf-8') if directory is not None else None
    try:
        for _ in range(3):
            descriptors = os.pipe()
            pipes.extend(descriptors)
            owned.update(descriptors)
        try:
            child = subprocess.Popen(
                arguments, executable=arguments[0], stdin=pipes[0],
                stdout=pipes[3], stderr=pipes[5], cwd=child_dir, env=child_env,
                close_fds=True, start_new_session=True, bufsize=0)
        except OSError as error:
            if error.errno in (errno.ENOENT, errno.ENOTDIR):
                _fail('not-found')
            if error.errno in (errno.EACCES, errno.EPERM):
                _fail('permission')
            _fail('spawn')
        except (ValueError, OverflowError):
            _fail('spawn')
        for index in (0, 3, 5):
            os.close(pipes[index])
            owned.remove(pipes[index])
        for name, index, mode in (('stdin', 1, 'wb'), ('stdout', 2, 'rb'),
                                  ('stderr', 4, 'rb')):
            setattr(child, name, os.fdopen(pipes[index], mode, buffering=0))
            owned.remove(pipes[index])
        return child
    except OSError:
        if child is not None:
            try:
                _kill_group(child)
            finally:
                _close_streams(child)
        _fail('io')
    finally:
        for descriptor in owned:
            try:
                os.close(descriptor)
            except OSError:
                pass


def proc_run(it, argv, stdin, cwd, env):
    raw_stdin, directory, environment = validate_request(argv, stdin, cwd, env)
    if os.name != 'posix':
        _fail('unsupported')
    deadline = time.monotonic() + PROC_TOTAL_TIMEOUT
    child = _spawn(argv, directory, environment)
    finished = False
    try:
        outputs = _communicate(child, raw_stdin, deadline)
        _remaining(deadline)
        stdout = outputs['stdout'].decode('utf-8')
        stderr = outputs['stderr'].decode('utf-8')
        _remaining(deadline)
        status = child.returncode
        exit_value = (Var('proc', 'Signaled', (-status,)) if status < 0
                      else Var('proc', 'Exited', (status,)))
        finished = True
        return Rec('proc.Result', (
            ('exit', exit_value), ('stdout', stdout), ('stderr', stderr)))
    except UnicodeError:
        _fail('invalid-utf8')
    except (OSError, ValueError):
        _fail('io')
    finally:
        # Killing after success is unnecessary; failures kill descendants even
        # if the leader exited while a grandchild kept a pipe open.
        try:
            if not finished:
                _kill_group(child)
        finally:
            _close_streams(child)


PROC_PRIMS = {'proc.run': proc_run}
