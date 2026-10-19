"""UTF-8 operating-system primitives. Host I/O errors become declared LM failures."""
from __future__ import annotations

import errno
import os
import stat

from .values import UNIT, LmFail, Var


def _read(it, line):
    try:
        source = getattr(it.stdin, 'buffer', it.stdin)
        raw = source.readline() if line else source.read()
        text = raw.decode('utf-8') if isinstance(raw, bytes) else raw
        if not line:
            return text
        if not text:
            return Var('', 'None')
        if text.endswith('\n'):
            text = text[:-1]
            if text.endswith('\r'):
                text = text[:-1]
        return Var('', 'Some', (text,))
    except (OSError, UnicodeError, ValueError) as ex:
        raise LmFail('io.IoError', (str(ex),)) from None


def io_args(it):
    return it.args


def io_read_line(it):
    return _read(it, True)


def io_read_all(it):
    return _read(it, False)


def io_eprint(it, s):
    it.err.write(s + '\n')
    it.err.flush()
    return UNIT


def fs_read(it, path):
    try:
        with open(path, encoding='utf-8', newline='') as f:
            return f.read()
    except (OSError, UnicodeError, ValueError) as ex:
        raise LmFail('fs.IoError', (path, str(ex))) from None


def fs_write(it, path, text):
    try:
        with open(path, 'w', encoding='utf-8', newline='') as f:
            f.write(text)
        return UNIT
    except (OSError, UnicodeError, ValueError) as ex:
        raise LmFail('fs.IoError', (path, str(ex))) from None


def fs_exists(it, path):
    try:
        os.stat(path)
        return True
    except OSError as ex:
        if ex.errno == errno.ENOENT:
            return False
        raise LmFail('fs.IoError', (path, str(ex))) from None
    except (UnicodeError, ValueError) as ex:
        raise LmFail('fs.IoError', (path, str(ex))) from None


def env_lookup(it, name):
    if not name or '=' in name or '\0' in name:
        return Var('', 'None')
    value = os.environ.get(name)
    if value is None:
        return Var('', 'None')
    value = value.encode('utf-8', errors='surrogateescape').decode('utf-8', errors='replace')
    return Var('', 'Some', (value,))


def fs_append(it, path, text):
    try:
        with open(path, 'ab') as f:
            f.write(text.encode('utf-8'))
        return UNIT
    except (OSError, UnicodeError, ValueError) as ex:
        raise LmFail('fs.IoError', (path, str(ex))) from None


def fs_entries(it, path):
    try:
        names = os.listdir(path)
        # listdir uses surrogateescape on Unix; reject those names instead of
        # letting host surrogate code points escape into LM strings.
        for name in names:
            name.encode('utf-8')
        return tuple(sorted(names))
    except (OSError, UnicodeError, ValueError) as ex:
        raise LmFail('fs.IoError', (path, str(ex))) from None


def fs_is_dir(it, path):
    try:
        return stat.S_ISDIR(os.stat(path).st_mode)
    except OSError as ex:
        if ex.errno in (errno.ENOENT, errno.ENOTDIR):
            return False
        raise LmFail('fs.IoError', (path, str(ex))) from None
    except (UnicodeError, ValueError) as ex:
        raise LmFail('fs.IoError', (path, str(ex))) from None


def fs_make_dir(it, path):
    try:
        os.mkdir(path)
        return UNIT
    except (OSError, UnicodeError, ValueError) as ex:
        raise LmFail('fs.IoError', (path, str(ex))) from None


def fs_remove(it, path):
    try:
        if stat.S_ISDIR(os.lstat(path).st_mode):
            os.rmdir(path)
        else:
            os.unlink(path)
        return UNIT
    except (OSError, UnicodeError, ValueError) as ex:
        raise LmFail('fs.IoError', (path, str(ex))) from None


def _claim_name(source, target):
    """Create `target` atomically (fails if it exists): a new symlink for a symlink, else a hard link."""
    if os.path.islink(source):
        os.symlink(os.readlink(source), target)
        return
    os.link(source, target)


def fs_rename(it, source, target):
    try:
        if '\0' in source or '\0' in target:
            raise ValueError('embedded null byte')
        if source == target:
            raise FileExistsError(errno.EEXIST, 'source equals target', source)
        if stat.S_ISDIR(os.lstat(source).st_mode):
            try:
                os.lstat(target)
            except FileNotFoundError:
                pass
            else:
                raise FileExistsError(errno.EEXIST, 'target exists', target)
            os.rename(source, target)
        else:
            _claim_name(source, target)
            os.unlink(source)
        return UNIT
    except (OSError, UnicodeError, ValueError) as ex:
        raise LmFail('fs.IoError', (source, str(ex))) from None


IO_PRIMS = {
    'io.args': io_args, 'io.read-line': io_read_line, 'io.read-all': io_read_all,
    'io.eprint': io_eprint, 'fs.read': fs_read, 'fs.write': fs_write, 'fs.exists': fs_exists,
    'env.lookup': env_lookup, 'fs.append': fs_append, 'fs.entries': fs_entries,
    'fs.is-dir': fs_is_dir, 'fs.make-dir': fs_make_dir,
    'fs.remove': fs_remove, 'fs.rename': fs_rename,
}
