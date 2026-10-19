"""Immutable 32-way vector trie with a tail; leaf traversal is linear.

The trie contains complete 32-element leaves, and the tail holds 1..32
elements (zero for the empty vector). Branches and leaves are immutable
tuples. Updates copy only their path and share every unaffected node.
"""
from __future__ import annotations

from dataclasses import dataclass
from itertools import islice


VEC_BITS = 5
VEC_WIDTH = 1 << VEC_BITS
VEC_MASK = VEC_WIDTH - 1


def _path(level, leaf):
    if level == 0:
        return leaf
    return (_path(level - VEC_BITS, leaf),)


def _push_tail(level, node, leaf, index):
    slot = (index >> level) & VEC_MASK
    if level == VEC_BITS:
        return node + (leaf,)
    child = (_push_tail(level - VEC_BITS, node[slot], leaf, index)
             if slot < len(node) else _path(level - VEC_BITS, leaf))
    return node[:slot] + (child,) + node[slot + 1:]


def _pop_tail(level, node, index):
    slot = (index >> level) & VEC_MASK
    if level == VEC_BITS:
        return node[:-1]
    child = _pop_tail(level - VEC_BITS, node[slot], index)
    if not child:
        return node[:slot]
    return node[:slot] + (child,)


def _set(level, node, index, value):
    slot = (index >> level) & VEC_MASK
    child = (value if level == 0
             else _set(level - VEC_BITS, node[slot], index, value))
    return node[:slot] + (child,) + node[slot + 1:]


def _leaves(level, node):
    if level == 0:
        yield node
        return
    for child in node:
        yield from _leaves(level - VEC_BITS, child)


@dataclass(frozen=True, eq=False)
class Vec:
    count: int = 0
    shift: int = VEC_BITS
    root: tuple = ()
    tail: tuple = ()

    @classmethod
    def from_iterable(cls, values):
        """Build bottom-up in O(n), including when values is a generator."""
        source = iter(values)
        leaves = []
        count = 0
        while True:
            leaf = tuple(islice(source, VEC_WIDTH))
            if not leaf:
                break
            leaves.append(leaf)
            count += len(leaf)
        if not leaves:
            return cls()
        tail = leaves.pop()
        shift = VEC_BITS
        while len(leaves) > VEC_WIDTH:
            leaves = [tuple(leaves[i:i + VEC_WIDTH])
                      for i in range(0, len(leaves), VEC_WIDTH)]
            shift += VEC_BITS
        return cls(count, shift, tuple(leaves), tail)

    def __len__(self):
        return self.count

    def __iter__(self):
        for leaf in _leaves(self.shift, self.root):
            yield from leaf
        yield from self.tail

    def __eq__(self, other):
        if not isinstance(other, Vec):
            return NotImplemented
        return (self.count == other.count
                and all(a == b for a, b in zip(self, other)))

    __hash__ = None

    def _leaf(self, index):
        if index >= self.count - len(self.tail):
            return self.tail
        node = self.root
        for level in range(self.shift, 0, -VEC_BITS):
            node = node[(index >> level) & VEC_MASK]
        return node

    def at(self, index):
        if not 0 <= index < self.count:
            raise IndexError(index)
        return self._leaf(index)[index & VEC_MASK]

    def set(self, index, value):
        if not 0 <= index < self.count:
            raise IndexError(index)
        if index >= self.count - len(self.tail):
            tail = _set(0, self.tail, index, value)
            return Vec(self.count, self.shift, self.root, tail)
        root = _set(self.shift, self.root, index, value)
        return Vec(self.count, self.shift, root, self.tail)

    def push(self, value):
        if len(self.tail) < VEC_WIDTH:
            return Vec(self.count + 1, self.shift, self.root,
                       self.tail + (value,))
        shift = self.shift
        if (self.count >> VEC_BITS) > (1 << shift):
            root = (self.root, _path(shift, self.tail))
            shift += VEC_BITS
        else:
            root = _push_tail(shift, self.root, self.tail, self.count - 1)
        return Vec(self.count + 1, shift, root, (value,))

    def pop(self):
        if not self.count:
            raise IndexError("empty vector")
        if self.count == 1:
            return Vec()
        if len(self.tail) > 1:
            return Vec(self.count - 1, self.shift, self.root, self.tail[:-1])
        tail = self._leaf(self.count - 2)
        root = _pop_tail(self.shift, self.root, self.count - 2)
        shift = self.shift
        if shift > VEC_BITS and len(root) == 1:
            root = root[0]
            shift -= VEC_BITS
        return Vec(self.count - 1, shift, root, tail)
