"""LM value adapters for the shared pattern compiler and Pike VM."""
from .pat_compile import compile_pattern, PatternError
from .pat_vm import search, find_iter
from .values import LmFail, Rec, Var


def compile_pat(it, s):
    try:
        return compile_pattern(s)
    except PatternError as ex:
        raise LmFail('pat.BadPattern', (ex.pos, ex.reason)) from None


def match_value(text, captures):
    groups = tuple(Var('', 'None') if start < 0
                   else Var('', 'Some', (text[start:end],))
                   for start, end in zip(captures[2::2], captures[3::2]))
    start, end = captures[:2]
    return Rec('pat.Match', (('start', start), ('end', end),
                             ('text', text[start:end]), ('groups', groups)))


def matches(it, text, pat):
    return search(pat, text, whole=True) is not None


def find(it, text, pat):
    captures = search(pat, text)
    if captures is None:
        return Var('', 'None')
    return Var('', 'Some', (match_value(text, captures),))


def find_all(it, text, pat):
    return tuple(match_value(text, caps) for caps in find_iter(pat, text))


def split(it, text, pat):
    out, previous = [], 0
    for captures in find_iter(pat, text):
        start, end = captures[:2]
        out.append(text[previous:start])
        previous = end
    return tuple(out) + (text[previous:],)


def replace_with(it, text, pat, replacement):
    out, previous = [], 0
    for captures in find_iter(pat, text):
        start, end = captures[:2]
        out.append(text[previous:start])
        out.append(it.apply(replacement, [match_value(text, captures)]))
        previous = end
    out.append(text[previous:])
    return ''.join(out)


def replace_all(it, text, pat, replacement):
    out, previous = [], 0
    for captures in find_iter(pat, text):
        start, end = captures[:2]
        out.extend((text[previous:start], replacement))
        previous = end
    return ''.join(out) + text[previous:]


PAT_PRIMS = {
    'pat.compile': compile_pat, 'pat.matches': matches, 'pat.find': find,
    'pat.find-all': find_all, 'pat.split': split,
    'pat.replace-all': replace_all, 'pat.replace-with': replace_with,
}
