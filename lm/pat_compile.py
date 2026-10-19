"""Bounded text-pattern parser and Thompson program compiler (ADR-075)."""
from dataclasses import dataclass


class PatternError(Exception):
    def __init__(self, pos, reason):
        super().__init__(reason)
        self.pos, self.reason = pos, reason


@dataclass(eq=False)
class Pat:
    code: list
    start: int
    groups: int
    scopes: list


DIGITS = ((48, 57),)
WORD = DIGITS + ((65, 90), (95, 95), (97, 122))
SPACE = ((9, 13), (32, 32))
SHORTHANDS = {'d': DIGITS, 'w': WORD, 's': SPACE}
META = frozenset(r'.^$*+?{}[]()|\-')


class Parser:
    def __init__(self, s):
        self.s, self.i, self.groups, self.depth = s, 0, 0, 0

    def error(self, pos, reason):
        raise PatternError(pos, reason)

    def alt(self):
        branches = [self.sequence()]
        while self.i < len(self.s) and self.s[self.i] == '|':
            self.i += 1
            branches.append(self.sequence())
        return ('alt', branches) if len(branches) > 1 else branches[0]

    def sequence(self):
        nodes = []
        while self.i < len(self.s) and self.s[self.i] not in ')|':
            node = self.atom()
            if self.i < len(self.s) and self.s[self.i] in '*+?{':
                node = self.repeat(node)
            nodes.append(node)
        return ('cat', nodes)

    def atom(self):
        p, c = self.i, self.s[self.i]
        self.i += 1
        if c in '*+?{':
            self.error(p, 'dangling quantifier')
        if c == '(':
            self.depth += 1
            if self.depth > 100:
                self.error(p, 'nesting limit')
            capture = True
            if self.s[self.i:self.i + 1] == '?':
                if self.s[self.i:self.i + 2] != '?:':
                    self.error(p, 'unsupported group')
                capture = False
                self.i += 2
            group = 0
            if capture:
                self.groups += 1
                group = self.groups
            node = self.alt()
            if self.i == len(self.s):
                self.error(p, 'unclosed group')
            self.i += 1
            self.depth -= 1
            return ('cap', group, node) if capture else node
        if c == '[':
            return self.character_class(p)
        if c == '\\':
            return self.escape(p)
        if c == '.':
            return ('any',)
        if c in '^$':
            return (c,)
        return ('char', ord(c))

    def escape(self, p):
        if self.i == len(self.s):
            self.error(p, 'trailing escape')
        c = self.s[self.i]
        self.i += 1
        if c.lower() in SHORTHANDS:
            return ('class', False, [(c.isupper(), SHORTHANDS[c.lower()])])
        if c in 'nt':
            return ('char', ord('\n' if c == 'n' else '\t'))
        if c in META:
            return ('char', ord(c))
        self.error(p, 'unknown escape')

    def class_item(self):
        p, c = self.i, self.s[self.i]
        self.i += 1
        return self.escape(p) if c == '\\' else ('char', ord(c))

    def character_class(self, p):
        negate = self.s[self.i:self.i + 1] == '^'
        self.i += int(negate)
        terms, first = [], True
        while self.i < len(self.s):
            if self.s[self.i] == ']' and not first:
                self.i += 1
                return ('class', negate, terms)
            leading_dash = first and self.s[self.i] == '-'
            a = self.class_item()
            first = False
            if (not leading_dash and self.i + 1 < len(self.s)
                    and self.s[self.i] == '-'
                    and self.s[self.i + 1] != ']'):
                dash = self.i
                self.i += 1
                b = self.class_item()
                if a[0] != 'char' or b[0] != 'char':
                    self.error(dash, 'invalid range')
                if a[1] > b[1]:
                    self.error(dash, 'reversed range')
                terms.append((False, ((a[1], b[1]),)))
                continue
            ranges = a[2] if a[0] == 'class' else [(False, ((a[1], a[1]),))]
            terms.extend(ranges)
        # A leading ] is literal only when a later ] closes the class.
        if self.s[p:] in ('[]', '[^]'):
            self.error(p, 'empty class')
        self.error(p, 'unclosed class')

    def repeat(self, node):
        p, c = self.i, self.s[self.i]
        self.i += 1
        if c in '*+?':
            lo, hi = {'*': (0, None), '+': (1, None), '?': (0, 1)}[c]
        else:
            start = self.i
            while self.i < len(self.s) and '0' <= self.s[self.i] <= '9':
                self.i += 1
            if start == self.i:
                self.error(p, 'invalid repetition')
            lo = self.number(start, p)
            hi = lo
            if self.s[self.i:self.i + 1] == ',':
                self.i += 1
                start = self.i
                while self.i < len(self.s) and '0' <= self.s[self.i] <= '9':
                    self.i += 1
                hi = self.number(start, p) if start < self.i else None
            if (self.s[self.i:self.i + 1] != '}'
                    or (hi is not None and hi < lo)):
                self.error(p, 'invalid repetition')
            self.i += 1
        lazy = self.s[self.i:self.i + 1] == '?'
        self.i += int(lazy)
        return ('rep', node, lo, hi, lazy)

    def number(self, start, p):
        digits = self.s[start:self.i].lstrip('0') or '0'
        if len(digits) > 4 or int(digits) > 1000:
            self.error(p, 'repetition bound')
        return int(digits)


class Compiler:
    def __init__(self):
        self.code = []
        self.scopes = []
        self.loops = ()

    def emit(self, *instruction):
        if len(self.code) == 10000:
            raise PatternError(0, 'program limit')
        self.code.append(instruction)
        self.scopes.append(self.loops)
        return len(self.code) - 1

    def node(self, n, end):
        op = n[0]
        if op == 'cat':
            for child in reversed(n[1]):
                end = self.node(child, end)
            return end
        if op == 'alt':
            start = self.node(n[1][-1], end)
            for child in reversed(n[1][:-1]):
                start = self.emit('split', self.node(child, end), start)
            return start
        if op == 'cap':
            close = self.emit('save', n[1] * 2 + 1, end)
            return self.emit('save', n[1] * 2, self.node(n[2], close))
        if op == 'rep':
            _, child, lo, hi, lazy = n
            if hi is None:
                split = self.emit('split', 0, 0)
                enclosing = self.loops
                self.loops += (split,)
                self.scopes[split] = self.loops
                guard = self.emit('guard', split, split, end)
                body = self.node(child, guard)
                mark = self.emit('mark', split, body)
                self.loops = enclosing
                branches = (end, mark) if lazy else (mark, end)
                self.code[split] = ('split', *branches)
                end = split
            else:
                final = end
                for _ in range(hi - lo):
                    split = self.emit('split', 0, 0)
                    enclosing = self.loops
                    self.loops += (split,)
                    self.scopes[split] = self.loops
                    guard = self.emit('guard', split, end, final)
                    body = self.node(child, guard)
                    mark = self.emit('mark', split, body)
                    self.loops = enclosing
                    branches = (final, mark) if lazy else (mark, final)
                    self.code[split] = ('split', *branches)
                    end = split
            for _ in range(lo):
                end = self.node(child, end)
            return end
        return self.emit(*n, end)


def compile_pattern(s):
    parser = Parser(s)
    tree = parser.alt()
    if parser.i != len(s):
        raise PatternError(parser.i, 'unexpected parenthesis')
    compiler = Compiler()
    end = compiler.emit('match')
    end = compiler.emit('save', 1, end)
    start = compiler.emit('save', 0, compiler.node(tree, end))
    return Pat(compiler.code, start, parser.groups, compiler.scopes)
