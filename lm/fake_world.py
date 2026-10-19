"""Hermetic effectful-example world; no operation reaches a host resource."""
from __future__ import annotations

from io import StringIO

from .io_prims import io_read_all, io_read_line
from .prims import PRIMS
from .rand_prims import SplitMix64
from .values import UNIT, LmFail, Var


def valid_path(path):
    """Absolute root or ordinary components; relative root is only implicit."""
    if not isinstance(path, str) or not path or '\0' in path:
        return False
    if path == '/':
        return True
    parts = path[1:].split('/') if path.startswith('/') else path.split('/')
    return all(part not in ('', '.', '..') for part in parts)


def parent_path(path):
    if path in ('.', '/'):
        return None
    if '/' not in path:
        return '.'
    return path.rsplit('/', 1)[0] or '/'


class FakeWorld:
    """Fresh mutable world shared by every nested call of one example.

    `given` contains evaluated `(clause_name, tuple(values))` pairs. The checker
    validates declarations first, so directory declarations may appear in any
    order. Roots `.` and `/` always exist and are distinct.
    """

    def __init__(self, given=()):
        self.args = ()
        self.stdin = StringIO()
        self.out = StringIO()
        self.err = StringIO()
        self.env = {}
        self.files = {}
        self.dirs = {'.', '/'}
        self.now_ms = 0
        seed = 0
        for name, values in given:
            if name == 'args':
                self.args = tuple(values)
            elif name == 'stdin':
                self.stdin = StringIO(values[0])
            elif name == 'env':
                self.env[values[0]] = values[1]
            elif name == 'file':
                self.files[values[0]] = values[1]
            elif name == 'dir':
                self.dirs.add(values[0])
            elif name == 'now-ms':
                self.now_ms = values[0]
            elif name == 'seed':
                seed = values[0]
        self.rng = SplitMix64(seed)

    def call(self, name, it, args):
        """Route effects here and delegate pure primitives normally."""
        if name.startswith('fs.'):
            return self._fs(name[3:], *args)
        if name in ('time.now-ms', 'time.mono-ms'):
            return self.now_ms
        if name == 'rand.int':
            return self.rng.int(*args)
        if name == 'rand.float':
            return self.rng.float()
        if name == 'io.args':
            return self.args
        if name == 'io.read-line':
            return io_read_line(self)
        if name == 'io.read-all':
            return io_read_all(self)
        if name in ('io.print', 'io.eprint'):
            stream = self.out if name == 'io.print' else self.err
            stream.write(args[0] + '\n')
            return UNIT
        if name == 'env.lookup':
            key = args[0]
            if not key or '=' in key or '\0' in key or key not in self.env:
                return Var('', 'None')
            return Var('', 'Some', (self.env[key],))
        return PRIMS[name](it, *args)

    def _fail(self, path, message):
        raise LmFail('fs.IoError', (path, message))

    def _path(self, path, error_path):
        if not valid_path(path):
            self._fail(error_path, 'invalid path')

    def _parent(self, path, error_path):
        if parent_path(path) not in self.dirs:
            self._fail(error_path, 'parent is not a directory')

    def _file_ancestor(self, path):
        p = parent_path(path)
        while p is not None:
            if p in self.files:
                return True
            p = parent_path(p)
        return False

    def _entries(self, path):
        return tuple(sorted(p.rsplit('/', 1)[-1]
                            for p in self.files.keys() | self.dirs
                            if parent_path(p) == path))

    def _fs(self, op, path, *args):
        self._path(path, path)
        if op == 'rename':
            return self._rename(path, args[0])
        if op == 'exists':
            if self._file_ancestor(path):
                self._fail(path, 'a path component is not a directory')
            return path in self.files or path in self.dirs
        if op == 'is-dir':
            return path in self.dirs
        if op == 'read':
            if path not in self.files:
                self._fail(path, 'not a regular file')
            return self.files[path]
        if op == 'entries':
            if path not in self.dirs:
                self._fail(path, 'not a directory')
            return self._entries(path)
        if op in ('write', 'append'):
            self._parent(path, path)
            if path in self.dirs:
                self._fail(path, 'is a directory')
            before = self.files.get(path, '') if op == 'append' else ''
            self.files[path] = before + args[0]
            return UNIT
        if op == 'make-dir':
            self._parent(path, path)
            if path in self.files or path in self.dirs:
                self._fail(path, 'path already exists')
            self.dirs.add(path)
            return UNIT
        if op == 'remove':
            if path in ('.', '/'):
                self._fail(path, 'cannot remove a root')
            if path in self.files:
                del self.files[path]
                return UNIT
            if path not in self.dirs:
                self._fail(path, 'path does not exist')
            if self._entries(path):
                self._fail(path, 'directory is not empty')
            self.dirs.remove(path)
            return UNIT
        raise RuntimeError(f'unknown fake filesystem operation {op}')

    def _rename(self, source, target):
        self._path(target, source)
        if source in ('.', '/'):
            self._fail(source, 'cannot rename a root')
        if source not in self.files and source not in self.dirs:
            self._fail(source, 'source does not exist')
        if target in self.files or target in self.dirs:
            self._fail(source, 'target already exists')
        self._parent(target, source)
        if source in self.files:
            self.files[target] = self.files.pop(source)
            return UNIT
        prefix = source + '/'
        if target.startswith(prefix):
            self._fail(source, 'cannot move a directory into itself')
        moved_dirs = {p for p in self.dirs
                      if p == source or p.startswith(prefix)}
        moved_files = {p: text for p, text in self.files.items()
                       if p.startswith(prefix)}
        self.dirs.difference_update(moved_dirs)
        self.dirs.update(target + p[len(source):] for p in moved_dirs)
        for path, text in moved_files.items():
            del self.files[path]
            self.files[target + path[len(source):]] = text
        return UNIT
