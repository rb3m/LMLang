"""Ordered Pike VM; unanchored search is O(program size * text length)."""


def accepts(instruction, c):
    op = instruction[0]
    if op == 'any':
        return c != '\n'
    cp = ord(c)
    if op == 'char':
        return cp == instruction[1]
    negate, terms = instruction[1:3]
    inside = any(any(lo <= cp <= hi for lo, hi in ranges) != neg
                 for neg, ranges in terms)
    return inside != negate


def search(pat, text, offset=0, whole=False):
    code, length = pat.code, len(text)
    current, candidate = [], None

    def add(out, seen, pc, captures, marks, pos):
        stack = [(pc, captures, marks)]
        while stack:
            pc, captures, marks = stack.pop()
            instruction = code[pc]
            op = instruction[0]
            # Only consuming instructions and matches are live threads. Epsilon
            # closure also distinguishes the number of enclosing loops entered
            # at this position, so a final empty iteration can update captures.
            # Nested entries are ordered, giving at most nesting-depth + 1
            # states per pc; the group limit bounds loop nesting by 101.
            key = pc if op in ('char', 'class', 'any', 'match') else (
                pc, sum(marks.get(loop) == pos for loop in pat.scopes[pc]))
            if key in seen:
                continue
            seen.add(key)
            if op == 'split':
                stack.append((instruction[2], captures.copy(), marks.copy()))
                stack.append((instruction[1], captures, marks))
            elif op == 'save':
                captures = captures.copy()
                captures[instruction[1]] = pos
                stack.append((instruction[2], captures, marks))
            elif op == 'mark':
                marks = {loop: marks[loop] for loop in pat.scopes[pc]
                         if loop in marks}
                marks[instruction[1]] = pos
                stack.append((instruction[2], captures, marks))
            elif op == 'guard':
                empty = marks.get(instruction[1]) == pos
                target = instruction[3] if empty else instruction[2]
                stack.append((target, captures, marks))
            elif op == '^':
                if pos == 0:
                    stack.append((instruction[1], captures, marks))
            elif op == '$':
                if pos == length:
                    stack.append((instruction[1], captures, marks))
            else:
                out.append((pc, captures, marks))

    for pos in range(offset, length + 1):
        if candidate is None and (not whole or pos == 0):
            seen = {pc for pc, _, _ in current}
            captures = [-1] * (2 * (pat.groups + 1))
            add(current, seen, pat.start, captures, {}, pos)
        following, seen = [], set()
        for pc, captures, marks in current:
            instruction = code[pc]
            if instruction[0] == 'match':
                if not whole or pos == length:
                    candidate = captures
                    break
                continue
            if pos < length and accepts(instruction, text[pos]):
                add(following, seen, instruction[-1], captures, marks, pos + 1)
        if candidate is not None and not following:
            return candidate
        current = following
        if whole and not current:
            return candidate
    return candidate


def find_iter(pat, text):
    offset = 0
    while offset <= len(text):
        captures = search(pat, text, offset)
        if captures is None:
            return
        yield captures
        start, end = captures[:2]
        offset = end + int(start == end)
