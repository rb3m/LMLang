"""Persistent vector structure and boundary semantics."""
import unittest

from lm.vector import Vec


class VectorTests(unittest.TestCase):
    def test_boundaries_and_sharing(self):
        for n in (0, 1, 31, 32, 33, 1024, 1025, 1056, 1057,
                  32768, 32769, 32800, 32801):
            with self.subTest(n=n):
                v = Vec.from_iterable(range(n))
                self.assertEqual(tuple(v), tuple(range(n)))
                pushed = v.push(n)
                self.assertEqual(tuple(pushed), tuple(range(n + 1)))
                self.assertEqual(pushed.pop(), v)
                if n:
                    self.assertEqual(tuple(v.pop()), tuple(range(n - 1)))
                    self.assertEqual(v.at(n - 1), n - 1)
                self.assertEqual(len(v), n)
        v = Vec.from_iterable(range(40000))
        updated = v.set(5, -1)
        self.assertEqual(v.at(5), 5)
        self.assertEqual(updated.at(5), -1)
        self.assertIs(v.root[1], updated.root[1])
        self.assertIs(v.root[0][1], updated.root[0][1])
        self.assertIs(v.tail, updated.tail)
        old_nodes = self.node_ids(v.root, v.shift)
        new_nodes = self.node_ids(updated.root, updated.shift)
        self.assertEqual(len(new_nodes - old_nodes), v.shift // 5 + 1)

    def test_history_independent_equality(self):
        v = Vec.from_iterable(range(1100))
        built = Vec()
        for i in range(1100):
            built = built.push(i)
        self.assertEqual(built, v)
        self.assertEqual(tuple(v.set(100, -1)),
                         tuple(range(100)) + (-1,) + tuple(range(101, 1100)))

    @staticmethod
    def node_ids(node, level):
        found = {id(node)}
        if level:
            for child in node:
                found.update(VectorTests.node_ids(child, level - 5))
        return found
