"""Map and Set values (ADR-049): tree invariants, shape-independent equality, printing round-trips."""
import random
import subprocess
import sys
import unittest
from pathlib import Path

from lm import tree
from lm.check import Checker
from lm.interp import Interp
from lm.loader import load
from lm.sexpr import read
from lm.values import UNIT, show

ROOT = Path(__file__).resolve().parents[2]


def check_avl(n, lo=None, hi=None) -> int:
    """Height of n after asserting order, balance, and the cached height and size."""
    if n is None:
        return 0
    k = n[tree.K]
    assert (lo is None or lo < k) and (hi is None or k < hi), "order"
    hl, hr = check_avl(n[tree.L], lo, k), check_avl(n[tree.R], k, hi)
    assert abs(hl - hr) <= 1, "balance"
    assert n[tree.H] == 1 + max(hl, hr) and n[tree.N] == 1 + tree.size(n[tree.L]) + tree.size(n[tree.R]), "cache"
    return 1 + max(hl, hr)


class Tree(unittest.TestCase):
    def test_random_puts_and_removes_keep_avl_invariants(self):
        rng = random.Random(49)
        root, model = None, {}
        for step in range(20000):
            k = rng.randrange(2000)
            if rng.random() < 0.4 and tree.find(root, k) is not None:
                root = tree.remove(root, k)
                del model[k]
            else:
                root = tree.insert(root, k, step)
                model[k] = step
            if step % 997 == 0:
                check_avl(root)
        check_avl(root)
        self.assertEqual(tree.items(root), sorted(model.items()))

    def test_equality_ignores_shape_and_history(self):
        keys = list(range(300))
        a = tree.build([(k, k) for k in keys], False)
        b = tree.build([(k, k) for k in reversed(keys)], False)
        root = tree.build([(k, k) for k in range(600)], False).root
        for k in range(300, 600):
            root = tree.remove(root, k)
        c = tree.Coll(root, False)
        self.assertEqual(a, b)
        self.assertEqual(a, c)
        self.assertNotEqual(tree.build([(1, UNIT)], True), tree.build([(1, UNIT)], False))
        self.assertNotEqual(a, tree.build([(k, k + 1) for k in keys], False))


class Printing(unittest.TestCase):
    def test_printed_values_read_back_as_constants(self):
        prog = load([str(ROOT / "stdlib")])
        Checker(prog).run()
        it, m = Interp(prog), prog.modules["map"]
        texts = ['(mapof ("b" (setof 2 1)) ("a" (setof)))', "(setof 2.5 -1.0 1e+16 1e-05)", "(mapof (true (list 1)) (false (list)))",
                 '(setof "日" "a" "" "B")', "(mapof (3 (Some 1)) (-9223372036854775808 None))", "(setof)", "(mapof)"]
        for text in texts:
            v = it.ev(read(text)[0], {}, m)
            printed = show(v)
            self.assertEqual(it.ev(read(printed)[0], {}, m), v, text)
            self.assertEqual(show(it.ev(read(printed)[0], {}, m)), printed, text)
        self.assertEqual(show(it.ev(read('(mapof ("b" 1) ("a" 2))')[0], {}, m)), '(mapof ("a" 2) ("b" 1))')

    def test_run_prints_in_key_order(self):
        p = subprocess.run([sys.executable, "-m", "lm", "run", "set.from-list", '(list "b" "a" "b")'], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual((p.returncode, p.stdout), (0, '(setof "a" "b")\n'))

    def test_run_rejects_non_key_instances(self):
        p = subprocess.run([sys.executable, "-m", "lm", "run", "set.from-list", "(list (list 1))"], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(p.returncode, 1)
        self.assertIn('"E-TYPE"', p.stdout + p.stderr)


if __name__ == "__main__":
    unittest.main()
