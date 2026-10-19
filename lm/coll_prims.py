"""Python implementations of the `map` and `set` prims (ADR-049 item 5). Go twins: lm/runtime/go/coll.go."""
from __future__ import annotations

from . import tree
from .values import UNIT, Pair, Var


def _opt(n):
    return Var("", "Some", (n[tree.V],)) if n is not None else Var("", "None", ())


def put(it, m, k, v):
    return m.with_root(tree.insert(m.root, k, v))


def at(it, m, k):
    return _opt(tree.find(m.root, k))


def has(it, m, k):
    return tree.find(m.root, k) is not None


def remove(it, m, k):
    return m if tree.find(m.root, k) is None else m.with_root(tree.remove(m.root, k))


def size(it, m):
    return tree.size(m.root)


def keys(it, m):
    return tuple(k for k, _ in tree.items(m.root))


def values(it, m):
    return tuple(v for _, v in tree.items(m.root))


def map_fold(it, m, init, step):
    acc = init
    for k, v in tree.items(m.root):
        acc = it.apply(step, [acc, k, v])
    return acc


def add(it, s, x):
    return put(it, s, x, UNIT)


def set_fold(it, s, init, step):
    acc = init
    for k, _ in tree.items(s.root):
        acc = it.apply(step, [acc, k])
    return acc


def union(it, s, t):
    """Inserts t's elements into s in ascending order (coll.go does the same)."""
    root = s.root
    for k, _ in tree.items(t.root):
        root = tree.insert(root, k, UNIT)
    return s.with_root(root)


def _keep(s, t, inside: bool):
    root = None
    for k, _ in tree.items(s.root):
        if (tree.find(t.root, k) is not None) == inside:
            root = tree.insert(root, k, UNIT)
    return s.with_root(root)


def intersect(it, s, t):
    return _keep(s, t, True)


def diff(it, s, t):
    return _keep(s, t, False)


def to_list(it, m):
    return tuple(Pair(k, v) for k, v in tree.items(m.root))


def from_list(it, ps):
    root = None
    for p in ps:
        root = tree.insert(root, p.a, p.b)
    return tree.Coll(root, False)


COLL_PRIMS = {
    "map.put": put, "map.at": at, "map.has": has, "map.remove": remove, "map.size": size,
    "map.keys": keys, "map.values": values, "map.fold": map_fold,
    "map.to-list": to_list, "map.from-list": from_list,
    "set.add": add, "set.has": has, "set.remove": remove, "set.size": size, "set.to-list": keys,
    "set.fold": set_fold, "set.union": union, "set.intersect": intersect, "set.diff": diff,
}
