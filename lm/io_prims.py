"""UTF-8 operating-system primitives. Host I/O errors become declared LM failures."""
from __future__ import annotations

import errno
import os

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


IO_PRIMS = {
    'io.args': io_args, 'io.read-line': io_read_line, 'io.read-all': io_read_all,
    'io.eprint': io_eprint, 'fs.read': fs_read, 'fs.write': fs_write, 'fs.exists': fs_exists,
}
