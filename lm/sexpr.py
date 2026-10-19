"""Reader: text -> positioned s-expression nodes. Never raises on user input."""
from __future__ import annotations

import re
import math
from dataclasses import dataclass, field

from .diag import Diagnostic, make

OPS = frozenset(["+", "-", "*", "/", "=", "!=", "<", "<=", ">", ">=", "->", "=>"])
INT_RE = re.compile(r"-?[0-9]+")
FLOAT_RE = re.compile(r"-?[0-9]+(\.[0-9]+)?([eE][+-]?[0-9]+)?")  # needs a `.` or an exponent (ADR-039)
SYM_RE = re.compile(r"([a-z][a-z0-9-]*\.)?[a-z][a-z0-9-]*")
WORDS = frozenset(["let?"])  # reserved symbols outside SYM_RE (ADR-045)
TYPE_RE = re.compile(r"([a-z][a-z0-9-]*\.)?[A-Z][A-Za-z0-9]*")
ESCAPES = {'"': '"', "\\": "\\", "n": "\n", "t": "\t"}
DELIMS = frozenset(' \t\r\n()"')


@dataclass(frozen=True)
class Atom:
    kind: str  # int | float | str | sym | type
    value: object
    line: int = 0
    col: int = 0
    raw: str = field(default="", compare=False)  # source text of a non-finite float literal (E-FLOAT)


@dataclass(frozen=True)
class SList:
    items: tuple
    line: int = 0
    col: int = 0


def to_data(node):
    """Position-free plain structure, for equality in tests."""
    if isinstance(node, Atom):
        return (node.kind, node.value)
    return tuple(to_data(i) for i in node.items)


def classify(tok: str, line: int, col: int):
    if INT_RE.fullmatch(tok):
        return Atom("int", int(tok), line, col)
    if FLOAT_RE.fullmatch(tok):
        v = float(tok) + 0.0  # + 0.0 turns -0.0 into 0.0 (ADR-039 item 4)
        return Atom("float", v, line, col, "" if math.isfinite(v) else tok)
    if tok in OPS or tok in WORDS or tok == "_" or SYM_RE.fullmatch(tok):
        return Atom("sym", tok, line, col)
    if TYPE_RE.fullmatch(tok):
        return Atom("type", tok, line, col)
    return None


def read(text: str, file: str = ""):
    """Return (single top-level node | None, diagnostics)."""
    n = len(text)
    i, line, col = 0, 1, 1
    stack: list = []  # [items, line, col]
    top: list = []
    sibling_open = None
    first_close = None  # where the first top-level form closed, for the "more forms follow" hint
    line_start = 0

    def bad(msg, l, c, found=""):
        return None, [make("E-PARSE", file, l, c, msg, found=found)]

    def early_close():
        nxt = top[1]
        return bad(f"file must contain exactly one top-level form: this `)` closes it, but more forms follow from line {nxt.line} col {nxt.col}; "
                   "look for an extra `)` before that line", *first_close, found=f"{len(top)} forms")

    while i < n:
        ch = text[i]
        if ch == "\n":
            i, line, col = i + 1, line + 1, 1
            line_start = i
        elif ch in " \t\r":
            i, col = i + 1, col + 1
        elif ch == "(":
            # A new line-leading form can reveal a missing close even if later
            # closing parens consume that form and leave only its ancestors open.
            # Indentation is only a diagnostic hint, never a syntax constraint.
            if (sibling_open is None and stack
                    and not text[line_start:i].strip()
                    and stack[-1][1] < line and col <= stack[-1][2]):
                sibling_open = (stack[-1][1], stack[-1][2])
            stack.append([[], line, col])
            i, col = i + 1, col + 1
        elif ch == ")":
            if not stack:
                return early_close() if len(top) > 1 else bad("unexpected `)`", line, col)
            items, l, c = stack.pop()
            if not stack and first_close is None:
                first_close = (line, col)
            (stack[-1][0] if stack else top).append(SList(tuple(items), l, c))
            i, col = i + 1, col + 1
        elif ch == '"':
            j, buf = i + 1, []
            while True:
                if j >= n or text[j] == "\n":
                    return bad("unterminated string", line, col)
                c = text[j]
                if c == '"':
                    break
                if ord(c) < 32 or (0x7F <= ord(c) <= 0x9F):
                    return bad("control character in string; use an escape", line, col + (j - i))
                if c == "\\":
                    if j + 1 >= n:
                        return bad("invalid escape `\\`", line, col + (j - i), found="\\")
                    nxt = text[j + 1]
                    if nxt in ESCAPES:
                        buf.append(ESCAPES[nxt])
                        j += 2
                    elif nxt == "u":
                        if j + 2 >= n or text[j + 2] != "{":
                            e = text[j + 1:j + 3] if j + 2 < n else text[j + 1:]
                            return bad(f"invalid escape `\\{e}`: expected `\\u{{H..}}`", line, col + (j - i), found="\\" + e)
                        close_idx = text.find("}", j + 3)
                        quote_idx = text.find('"', j + 3)
                        nl_idx = text.find("\n", j + 3)
                        limit = n
                        if quote_idx != -1: limit = min(limit, quote_idx)
                        if nl_idx != -1: limit = min(limit, nl_idx)
                        if close_idx == -1 or close_idx >= limit:
                            found_text = text[j:limit]
                            return bad(f"unterminated unicode escape `{found_text}`", line, col + (j - i), found=found_text)
                        hex_str = text[j + 3:close_idx]
                        if not hex_str:
                            return bad("empty unicode escape `\\u{}`", line, col + (j - i), found="\\u{}")
                        if len(hex_str) > 6:
                            return bad(f"unicode escape too large: `\\u{{{hex_str}}}` has {len(hex_str)} hex digits (maximum 6)", line, col + (j - i), found=f"\\u{{{hex_str}}}")
                        if not all(ch in "0123456789abcdefABCDEF" for ch in hex_str):
                            return bad(f"invalid hex digit in unicode escape `\\u{{{hex_str}}}`", line, col + (j - i), found=f"\\u{{{hex_str}}}")
                        cp = int(hex_str, 16)
                        if cp > 0x10FFFF:
                            return bad(f"unicode escape out of range: `U+{cp:X}` > U+10FFFF", line, col + (j - i), found=f"\\u{{{hex_str}}}")
                        if 0xD800 <= cp <= 0xDFFF:
                            return bad(f"unicode escape cannot be a surrogate: `U+{cp:04X}`", line, col + (j - i), found=f"\\u{{{hex_str}}}")
                        buf.append(chr(cp))
                        j = close_idx + 1
                    else:
                        return bad(f"invalid escape `\\{nxt}`", line, col + (j - i), found="\\" + nxt)
                else:
                    buf.append(c)
                    j += 1
            (stack[-1][0] if stack else top).append(Atom("str", "".join(buf), line, col))
            col += j + 1 - i
            i = j + 1
        else:
            j = i
            while j < n and text[j] not in DELIMS:
                j += 1
            tok = text[i:j]
            atom = classify(tok, line, col)
            if atom is None:
                return bad(f"invalid token `{tok}`", line, col, found=tok)
            (stack[-1][0] if stack else top).append(atom)
            col += j - i
            i = j

    if stack:
        return bad("unclosed `(`", *(sibling_open or (stack[-1][1], stack[-1][2])))
    if len(top) > 1:
        return early_close()
    if len(top) != 1:
        return bad("file must contain exactly one top-level form", 1, 1, found=f"{len(top)} forms")
    return top[0], []
