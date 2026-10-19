"""Canonical printer: the single definition of LM text form (docs/SPEC.md section 2)."""
from __future__ import annotations

from .ast import canonicalize
from .diag import has_errors
from .sexpr import Atom, SList, read

WIDTH = 100
_ESC = {'"': '\\"', "\\": "\\\\", "\n": "\\n", "\t": "\\t"}


def escape_str(s: str) -> str:
    out = []
    for c in s:
        e = _ESC.get(c)
        if e is not None:
            out.append(e)
            continue
        cp = ord(c)
        if cp < 0x20 or (0x7F <= cp <= 0x9F):
            out.append(f"\\u{{{cp:x}}}")
        else:
            out.append(c)
    return '"' + "".join(out) + '"'


def flat(n) -> str:
    if isinstance(n, SList):
        return "(" + " ".join(flat(i) for i in n.items) + ")"
    if n.kind == "str":
        return escape_str(n.value)
    if n.kind == "float":
        return n.raw or float_text(n.value)
    return str(n.value)


def float_text(x: float) -> str:
    """Canonical Float text = Python's repr (ADR-039 item 6): shortest round-trip digits, positional
    for decimal exponents in [-4, 16) (always with a `.`), else `d[.ddd]e+XX`. -0.0 prints `0.0`."""
    return repr(x + 0.0)


def render(n, ind: int) -> str:
    """Text for node starting at column `ind`; continuation lines carry absolute indent."""
    f = flat(n)
    if isinstance(n, Atom) or not n.items or ind + len(f) <= WIDTH:
        return f
    first = n.items[0]
    if isinstance(first, Atom):
        head, rest = "(" + flat(first), n.items[1:]
    else:
        head, rest = "(", n.items
    pad = " " * (ind + 2)
    return head + "".join("\n" + pad + render(a, ind + 2) for a in rest) + ")"


def _is_fn(n) -> bool:
    return isinstance(n, SList) and n.items and isinstance(n.items[0], Atom) and n.items[0].value == "fn"


def _block(node, ind: int) -> str:
    head = "(" + flat(node.items[0]) + " " + flat(node.items[1])
    kids = node.items[2:]
    if not kids:
        return head + ")"
    pad = " " * (ind + 2)
    return head + "".join("\n" + pad + (_block(k, ind + 2) if _is_fn(k) else render(k, ind + 2)) for k in kids) + ")"


def print_module(m) -> str:
    return _block(m, 0) + "\n"


def format_text(text: str, file: str = ""):
    """Return (canonical text | None, diagnostics)."""
    root, diags = read(text, file)
    if root is None:
        return None, diags
    canon, d2 = canonicalize(root, file)
    diags = diags + d2
    if canon is None or has_errors(diags):
        return None, diags
    return print_module(canon), diags
