"""String parsing semantics independent of host numeric parsing limits."""
import re

from .unicode_tables import to_lower_str, to_upper_str
from .values import LmFail, Var

NONE = Var('', 'None')

TRIM_CHARS = "".join(chr(cp) for cp in (
    *range(0x09, 0x0E), *range(0x1C, 0x21), 0x85, 0xA0, 0x1680,
    *range(0x2000, 0x200B), 0x2028, 0x2029, 0x202F, 0x205F, 0x3000
))


def split(it, s, sep):
    return tuple(s.split(sep)) if sep else tuple(s)


def trim(it, s):
    return s.strip(TRIM_CHARS)


def to_int(it, s):
    if not re.fullmatch(r'[+-]?[0-9]+', s):
        return NONE
    negative = s.startswith('-')
    digits = s.lstrip('+-').lstrip('0') or '0'
    bound = '9223372036854775808' if negative else '9223372036854775807'
    if len(digits) > len(bound) or (len(digits) == len(bound) and digits > bound):
        return NONE
    value = int(digits)
    return Var('', 'Some', (-value if negative else value,))


def starts_with(it, s, prefix):
    return s.startswith(prefix)


def contains(it, s, part):
    return part in s


def substring(it, s, start, end):
    if not 0 <= start <= end <= len(s):
        raise LmFail('OutOfRange')
    return s[start:end]


def lines(it, s):
    if not s:
        return ()
    parts = re.split(r'\r\n|[\r\n]', s)
    if parts[-1] == '':
        parts.pop()
    return tuple(parts)


def index_of(it, s, part):
    i = s.find(part)
    return NONE if i < 0 else Var('', 'Some', (i,))


def repeat(it, s, n):
    return s * max(n, 0)


def replace(it, s, old, new):
    return s.replace(old, new) if old else s


_UPPER = str.maketrans('abcdefghijklmnopqrstuvwxyz', 'ABCDEFGHIJKLMNOPQRSTUVWXYZ')
_LOWER = str.maketrans('ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz')


def upper_ascii(it, s):
    return s.translate(_UPPER)


def lower_ascii(it, s):
    return s.translate(_LOWER)


def to_codes(it, s):
    return tuple(ord(c) for c in s)


def from_codes(it, cs):
    for c in cs:
        if c < 0 or c > 0x10FFFF or (0xD800 <= c <= 0xDFFF):
            raise LmFail('str.BadCode', (c,))
    return "".join(chr(c) for c in cs)


def upper(it, s):
    return to_upper_str(s)


def lower(it, s):
    return to_lower_str(s)


STR_PRIMS = {
    'str.split': split, 'str.trim': trim, 'str.to-int': to_int,
    'str.starts-with': starts_with, 'str.contains': contains,
    'str.substring': substring, 'str.lines': lines,
    'str.index-of': index_of, 'str.repeat': repeat, 'str.replace': replace,
    'str.upper-ascii': upper_ascii, 'str.lower-ascii': lower_ascii,
    'str.to-codes': to_codes, 'str.from-codes': from_codes,
    'str.upper': upper, 'str.lower': lower,
}
