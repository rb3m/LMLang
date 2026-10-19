"""Python implementations of stdlib `(prim "name")` bodies."""
from __future__ import annotations

from .values import UNIT, LmFail, Var
from .coll_prims import COLL_PRIMS
from .float_prims import FLOAT_PRIMS
from .io_prims import IO_PRIMS
from .str_prims import STR_PRIMS
from .rand_prims import RAND_PRIMS
from .json_prims import JSON_PRIMS


def list_concat(it, xs, ys):
    return xs + ys


def list_filter(it, xs, keep):
    return tuple(x for x in xs if it.apply(keep, [x]) is True)


def list_fold(it, xs, init, step):
    acc = init
    for x in xs:
        acc = it.apply(step, [acc, x])
    return acc


def list_map(it, xs, f):
    return tuple(it.apply(f, [x]) for x in xs)


def list_any(it, xs, pred):
    return any(it.apply(pred, [x]) for x in xs)


def list_all(it, xs, pred):
    return all(it.apply(pred, [x]) for x in xs)


def list_map2(it, xs, ys, f):
    return tuple(it.apply(f, [x, y]) for x, y in zip(xs, ys))


def list_index_of(it, xs, target):
    return Var("", "Some", (xs.index(target),)) if target in xs else Var("", "None", ())


def list_nth(it, xs, i):
    if not 0 <= i < len(xs):
        raise LmFail("OutOfRange")
    return xs[i]


def list_at(it, xs, i):
    return Var("", "Some", (xs[i],)) if 0 <= i < len(xs) else Var("", "None", ())


def list_take(it, xs, n):
    return xs[:max(n, 0)]


def list_drop(it, xs, n):
    return xs[max(n, 0):]


def list_sort_by(it, xs, less):
    """Stable top-down merge sort; lm/runtime/go/prims.go runs the same steps, so the sequence of
    `less` calls (and the result even for an inconsistent `less`) is identical (ADR-045)."""
    if len(xs) <= 1:
        return xs
    mid = len(xs) // 2
    a, b = list_sort_by(it, xs[:mid], less), list_sort_by(it, xs[mid:], less)
    out, i, j = [], 0, 0
    while i < len(a) and j < len(b):
        if it.apply(less, [b[j], a[i]]) is True:
            out.append(b[j])
            j += 1
            continue
        out.append(a[i])
        i += 1
    return tuple(out) + a[i:] + b[j:]


def list_range(it, start, stop):
    return tuple(range(start, stop))


def list_reverse(it, xs):
    return tuple(reversed(xs))


def str_concat(it, a, b):
    return a + b


def str_from_int(it, n):
    return str(n)


def str_join(it, parts, sep):
    return sep.join(parts)


def str_length(it, s):
    return len(s)


def io_print(it, s):
    it.out.write(s + "\n")
    it.out.flush()
    return UNIT


PRIMS = {
    **JSON_PRIMS, **IO_PRIMS, **STR_PRIMS, **FLOAT_PRIMS, **COLL_PRIMS, **RAND_PRIMS,
    "list.concat": list_concat, "list.filter": list_filter, "list.fold": list_fold, "list.map": list_map,
    "list.any": list_any, "list.all": list_all, "list.map2": list_map2, "list.index-of": list_index_of,
    "list.nth": list_nth, "list.at": list_at, "list.take": list_take, "list.drop": list_drop,
    "list.sort-by": list_sort_by, "list.range": list_range, "list.reverse": list_reverse,
    "str.concat": str_concat, "str.from-int": str_from_int, "str.join": str_join, "str.length": str_length,
    "io.print": io_print,
}
