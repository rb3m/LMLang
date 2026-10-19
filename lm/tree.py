"""Map and Set values: a persistent AVL tree (ADR-049 item 3). lm/runtime/go/coll.go runs the same
algorithm step for step. Semantics never depend on the tree's shape: equality and every traversal
use the ascending key order (Int and Float numerically, Str by code point, false < true).

A node is a tuple (key, value, left, right, height, size); the empty tree is None. Sets store UNIT
as every value. Keys of one tree all have the same LM type, so Python's `<` orders them.
"""
from __future__ import annotations

K, V, L, R, H, N = range(6)


def height(n) -> int:
    return n[H] if n else 0


def size(n) -> int:
    return n[N] if n else 0


def node(k, v, left, right):
    return (k, v, left, right, 1 + max(height(left), height(right)), 1 + size(left) + size(right))


def balance(k, v, left, right):
    """Node (k, v, left, right) whose subtrees differ in height by at most 2, rebalanced by rotation."""
    hl, hr = height(left), height(right)
    if hl > hr + 1:
        if height(left[L]) >= height(left[R]):
            return node(left[K], left[V], left[L], node(k, v, left[R], right))
        lr = left[R]
        return node(lr[K], lr[V], node(left[K], left[V], left[L], lr[L]), node(k, v, lr[R], right))
    if hr > hl + 1:
        if height(right[R]) >= height(right[L]):
            return node(right[K], right[V], node(k, v, left, right[L]), right[R])
        rl = right[L]
        return node(rl[K], rl[V], node(k, v, left, rl[L]), node(right[K], right[V], rl[R], right[R]))
    return node(k, v, left, right)


def insert(n, k, v):
    """Tree with k bound to v (an existing binding of k is replaced)."""
    if n is None:
        return node(k, v, None, None)
    if k < n[K]:
        return balance(n[K], n[V], insert(n[L], k, v), n[R])
    if n[K] < k:
        return balance(n[K], n[V], n[L], insert(n[R], k, v))
    return node(k, v, n[L], n[R])


def find(n, k):
    """The node holding k, or None."""
    while n is not None:
        if k < n[K]:
            n = n[L]
        elif n[K] < k:
            n = n[R]
        else:
            return n
    return None


def _remove_min(n):
    if n[L] is None:
        return n[R]
    return balance(n[K], n[V], _remove_min(n[L]), n[R])


def _min(n):
    while n[L] is not None:
        n = n[L]
    return n


def remove(n, k):
    """Tree without k; k must be present (callers test with find first)."""
    if k < n[K]:
        return balance(n[K], n[V], remove(n[L], k), n[R])
    if n[K] < k:
        return balance(n[K], n[V], n[L], remove(n[R], k))
    if n[L] is None:
        return n[R]
    if n[R] is None:
        return n[L]
    m = _min(n[R])
    return balance(m[K], m[V], n[L], _remove_min(n[R]))


def items(n) -> list:
    """(key, value) pairs in ascending key order."""
    out, stack = [], []
    while stack or n is not None:
        while n is not None:
            stack.append(n)
            n = n[L]
        n = stack.pop()
        out.append((n[K], n[V]))
        n = n[R]
    return out


class Coll:
    """An LM Map (is_set False) or Set (is_set True) value. Immutable."""
    __slots__ = ("root", "is_set")

    def __init__(self, root, is_set: bool):
        self.root, self.is_set = root, is_set

    def __eq__(self, other):
        return (isinstance(other, Coll) and self.is_set == other.is_set and size(self.root) == size(other.root)
                and items(self.root) == items(other.root))

    def __hash__(self):
        return hash(tuple(items(self.root)))

    def with_root(self, root):
        return Coll(root, self.is_set)


def build(pairs, is_set: bool) -> Coll:
    """A Map from (key, value) pairs inserted in order, or a Set when is_set (values ignored)."""
    root = None
    for k, v in pairs:
        root = insert(root, k, v)
    return Coll(root, is_set)
