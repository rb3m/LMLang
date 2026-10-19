"""Strict RFC 8259 JSON, with code-point diagnostics shared with runtime/go/json.go.

No host JSON library: grammar, duplicate keys and Unicode escape validation are explicit.
"""
import math

from . import tree
from .printer import float_text
from .values import INT_MIN, INT_MAX, LmFail, Var


def variant(name, *args):
    return Var('json', name, args)


class Parser:
    def __init__(self, text):
        self.s, self.i = text, 0

    def bad(self, msg):
        raise LmFail('json.BadJson', (self.i, msg))

    def peek(self):
        return self.s[self.i] if self.i < len(self.s) else ''

    def required(self):
        c = self.peek()
        if not c:
            self.bad('unexpected end')
        return c

    def space(self):
        while self.peek() and self.peek() in ' \t\r\n':
            self.i += 1

    def expect(self, c):
        if self.required() != c:
            self.bad('unexpected character')
        self.i += 1

    def hex4(self):
        n = 0
        for _ in range(4):
            c = self.required()
            if c not in '0123456789abcdefABCDEF':
                self.bad('bad escape')
            n = n * 16 + int(c, 16)
            self.i += 1
        return n

    def string(self):
        self.expect('"')
        out = []
        escapes = {'"': '"', '\\': '\\', '/': '/', 'b': '\b', 'f': '\f',
                   'n': '\n', 'r': '\r', 't': '\t'}
        while True:
            c = self.required()
            if c == '"':
                self.i += 1
                return ''.join(out)
            if ord(c) < 32:
                self.bad('control character in string')
            self.i += 1
            if c != '\\':
                out.append(c)
                continue
            c = self.required()
            if c in escapes:
                out.append(escapes[c])
                self.i += 1
                continue
            if c != 'u':
                self.bad('bad escape')
            self.i += 1
            n = self.hex4()
            if 0xD800 <= n <= 0xDBFF:
                if self.s[self.i:self.i + 2] != '\\u':
                    self.bad('unpaired surrogate')
                self.i += 2
                lo = self.hex4()
                if not 0xDC00 <= lo <= 0xDFFF:
                    self.bad('unpaired surrogate')
                n = 0x10000 + ((n - 0xD800) << 10) + lo - 0xDC00
            elif 0xDC00 <= n <= 0xDFFF:
                self.bad('unpaired surrogate')
            out.append(chr(n))

    def digits(self):
        c = self.required()
        if not '0' <= c <= '9':
            self.bad('unexpected character')
        while self.peek() and '0' <= self.peek() <= '9':
            self.i += 1

    def number(self):
        start = self.i
        if self.peek() == '-':
            self.i += 1
        if self.required() == '0':
            self.i += 1
        else:
            self.digits()
        integer = True
        if self.peek() == '.':
            integer = False
            self.i += 1
            self.digits()
        if self.peek() and self.peek() in 'eE':
            integer = False
            self.i += 1
            if self.peek() and self.peek() in '+-':
                self.i += 1
            self.digits()
        text = self.s[start:self.i]
        # Bound by length first; never hit Python's host integer-string digit limit.
        if integer and len(text.lstrip('-')) <= 19:
            n = int(text)
            if INT_MIN <= n <= INT_MAX:
                return variant('JInt', n)
        n = float(text)
        if not math.isfinite(n):
            self.bad('number out of range')
        return variant('JFloat', 0.0 if n == 0 else n)

    def value(self):
        """Explicit container stack, so JSON nesting never consumes the Python call stack."""
        stack = []
        while True:
            self.space()
            c = self.required()
            if c in '[{':
                self.i += 1
                stack.append([c, [] if c == '[' else None, None])
                self.space()
                if self.peek() == (']' if c == '[' else '}'):
                    self.i += 1
                    frame = stack.pop()
                    v = self.container(frame)
                else:
                    if c == '{':
                        stack[-1][2] = self.key(stack[-1])
                    continue
            elif c == '"':
                v = variant('JStr', self.string())
            elif c == '-' or '0' <= c <= '9':
                v = self.number()
            else:
                word = {'n': 'null', 't': 'true', 'f': 'false'}.get(c)
                if word is None:
                    self.bad('unexpected character')
                for ch in word:
                    self.expect(ch)
                v = variant('JNull') if word == 'null' else variant('JBool', word == 'true')
            while stack:
                frame = stack[-1]
                if frame[0] == '[':
                    frame[1].append(v)
                else:
                    frame[1] = tree.insert(frame[1], frame[2], v)
                self.space()
                if self.required() == (']' if frame[0] == '[' else '}'):
                    self.i += 1
                    v = self.container(stack.pop())
                    continue
                self.expect(',')
                self.space()
                if frame[0] == '{':
                    frame[2] = self.key(frame)
                break
            else:
                return v

    def key(self, frame):
        key = self.string()
        if tree.find(frame[1], key) is not None:
            self.bad('duplicate key')
        self.space()
        self.expect(':')
        return key

    @staticmethod
    def container(frame):
        return (variant('JArr', tuple(frame[1])) if frame[0] == '['
                else variant('JObj', tree.Coll(frame[1], False)))


def parse(it, s):
    p = Parser(s)
    value = p.value()
    p.space()
    if p.peek():
        p.bad('trailing data')
    return value


def quote(s):
    escapes = {'"': '\\"', '\\': '\\\\', '\b': '\\b', '\f': '\\f',
               '\n': '\\n', '\r': '\\r', '\t': '\\t'}
    return '"' + ''.join(escapes.get(c, f'\\u{ord(c):04X}' if ord(c) < 32 else c)
                         for c in s) + '"'


def print_json(it, j):
    out, pending = [], [j]
    while pending:
        v = pending.pop()
        if isinstance(v, str):  # literal output token
            out.append(v)
            continue
        name, args = v.name, v.args
        if name == 'JNull':
            out.append('null')
        elif name == 'JBool':
            out.append('true' if args[0] else 'false')
        elif name == 'JInt':
            out.append(str(args[0]))
        elif name == 'JFloat':
            out.append(float_text(args[0]))
        elif name == 'JStr':
            out.append(quote(args[0]))
        else:
            obj = name == 'JObj'
            out.append('{' if obj else '[')
            tokens = []
            for k, x in (tree.items(args[0].root) if obj else enumerate(args[0])):
                if tokens:
                    tokens.append(',')
                if obj:
                    tokens.extend((quote(k), ':'))
                tokens.append(x)
            tokens.append('}' if obj else ']')
            pending.extend(reversed(tokens))
    return ''.join(out)


JSON_PRIMS = {'json.parse': parse, 'json.print': print_json}
