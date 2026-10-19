"""Persistent vector primitives; all bulk operations traverse leaves once."""
from __future__ import annotations

from .values import LmFail, Var
from .vector import Vec


NONE = Var("", "None", ())


def _some(value):
    return Var("", "Some", (value,))


def empty(it):
    return Vec()


def from_list(it, xs):
    return Vec.from_iterable(xs)


def to_list(it, v):
    return tuple(v)


def size(it, v):
    return len(v)


def at(it, v, i):
    return _some(v.at(i)) if 0 <= i < len(v) else NONE


def set_value(it, v, i, x):
    return _some(v.set(i, x)) if 0 <= i < len(v) else NONE


def push(it, v, x):
    return v.push(x)


def pop(it, v):
    return _some(v.pop()) if len(v) else NONE


def last(it, v):
    return _some(v.tail[-1]) if len(v) else NONE


def fold(it, v, init, step):
    acc = init
    for x in v:
        acc = it.apply(step, [acc, x])
    return acc


def map_value(it, v, f):
    return Vec.from_iterable(it.apply(f, [x]) for x in v)


def repeat(it, n, x):
    return Vec.from_iterable(x for _ in range(max(0, n)))


def tabulate(it, n, f):
    return Vec.from_iterable(it.apply(f, [i]) for i in range(max(0, n)))


def nth(it, v, i):
    if not 0 <= i < len(v):
        raise LmFail("OutOfRange")
    return v.at(i)


def put(it, v, i, x):
    if not 0 <= i < len(v):
        raise LmFail("OutOfRange")
    return v.set(i, x)


VEC_PRIMS = {
    "vec.empty": empty, "vec.from-list": from_list, "vec.to-list": to_list,
    "vec.size": size, "vec.at": at, "vec.set": set_value,
    "vec.push": push, "vec.pop": pop, "vec.last": last, "vec.fold": fold,
    "vec.map": map_value, "vec.repeat": repeat, "vec.tabulate": tabulate,
    "vec.nth": nth, "vec.put": put,
}
