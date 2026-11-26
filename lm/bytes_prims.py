"""Immutable byte sequence primitives shared by the Python runtimes."""
from binascii import unhexlify
from itertools import product

from .values import Var


NONE = Var("", "None", ())


def some(value):
    return Var("", "Some", (value,))


def parse_hex(text):
    """Decode ASCII hex pairs, or return None for invalid input."""
    try:
        return unhexlify(text)
    except ValueError:
        return None


def at(it, data, index):
    return some(data[index]) if 0 <= index < len(data) else NONE


def slice_bytes(it, data, start, count):
    start = min(len(data), max(0, start))
    count = min(len(data) - start, max(0, count))
    return data[start:start + count]


def fill(it, count, value):
    if not 0 <= value <= 255:
        return NONE
    return some(bytes([value]) * max(0, count))


def from_list(it, values):
    if any(not 0 <= value <= 255 for value in values):
        return NONE
    return some(bytes(values))


def from_hex(it, text):
    data = parse_hex(text)
    return NONE if data is None else some(data)


def to_str(it, data):
    try:
        return some(data.decode("utf-8"))
    except UnicodeDecodeError:
        return NONE


def get_field(width, order, signed):
    def get(it, data, offset):
        if not 0 <= offset <= len(data) - width:
            return NONE
        field = data[offset:offset + width]
        return some(int.from_bytes(field, order, signed=signed))

    return get


def put_field(width, order, signed):
    bits = 8 * width
    limit = 1 << (bits - int(signed))
    minimum = -limit if signed else 0

    def put(it, data, offset, value):
        if not (0 <= offset <= len(data) - width and minimum <= value < limit):
            return NONE
        field = value.to_bytes(width, order, signed=signed)
        return some(data[:offset] + field + data[offset + width:])

    return put


BYTES_PRIMS = {
    "bytes.empty": lambda it: b"",
    "bytes.size": lambda it, data: len(data),
    "bytes.at": at,
    "bytes.slice": slice_bytes,
    "bytes.concat": lambda it, left, right: left + right,
    "bytes.fill": fill,
    "bytes.from-list": from_list,
    "bytes.to-list": lambda it, data: tuple(data),
    "bytes.hex": lambda it, data: data.hex(),
    "bytes.from-hex": from_hex,
    "bytes.from-str": lambda it, text: text.encode("utf-8"),
    "bytes.to-str": to_str,
}

SIGNS = (("u", False), ("s", True))
FIELDS = (
    ("8", 1, "big"), ("16le", 2, "little"), ("16be", 2, "big"),
    ("32le", 4, "little"), ("32be", 4, "big"),
)
for (prefix, signed), (suffix, width, order) in product(SIGNS, FIELDS):
    BYTES_PRIMS[f"bytes.{prefix}{suffix}"] = get_field(width, order, signed)
    BYTES_PRIMS[f"bytes.put-{prefix}{suffix}"] = put_field(width, order, signed)
