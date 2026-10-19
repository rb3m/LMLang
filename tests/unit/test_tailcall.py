"""Self tail-call semantics, including contract diagnostics and forbidden contexts."""
import unittest
from pathlib import Path

from lm.check import Checker
from lm.interp import Interp
from lm.loader import load
from lm.lower import lower
from lm.runner import example_outcomes, runtime_diag
from lm.sexpr import read
from lm.tailcall import tail_sites
from lm.values import Violation

ROOT = Path(__file__).resolve().parents[2]


class TailCalls(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.prog = load([str(ROOT / 'tests/spec/run/tailcall.lm')])
        Checker(cls.prog).run()
        assert not cls.prog.diags, cls.prog.diags

    def test_deep_loop_and_captures_succeed(self):
        outcomes = example_outcomes(self.prog, ['tailcall'])
        for fn, value in [('loop', '(Some 1000000)'), ('captures', '(list 2 4 6)'),
                          ('swap', '21'), ('checked', '100'), ('guarded', '99')]:
            self.assertEqual(outcomes[f'tailcall/{fn}/example#0'], ('ok', value))
        self.assertEqual(outcomes['tailcall/non-tail/example#0'], ('fault', 'E-RECURSION-LIMIT'))

    def test_contract_fault_preserves_inner_invocation(self):
        for name, code, clause in [('inner-bad', 'E-ENSURES-VIOLATED', 'ensures#0'),
                                   ('entry-bad', 'E-REQUIRES-VIOLATED', 'requires#0')]:
            it = Interp(self.prog)
            with self.assertRaises(Violation) as raised:
                it.call_fn(self.prog.modules['tailcall'].fns[name], [3])
            d = runtime_diag(raised.exception, it=it)
            self.assertEqual((d.code, d.path, d.found), (code, f'tailcall/{name}/{clause}', '(2)'))
            self.assertEqual(it.frames[-1][1].name, name)
            self.assertEqual(it.frames[-1][3], [2])
            it = Interp(self.prog, contracts=False)
            self.assertEqual(it.call_fn(self.prog.modules['tailcall'].fns[name], [3]), 0)

    def test_shared_sites_exclude_all_non_tail_contexts(self):
        # Only the last self call is eligible; nothing under these other forms is.
        text = '''(do (f 1) (if (f 2)
          (let ((x (f 3))) (let? ((y (f 4)))
            (match (f 5) (_ (f 6)))))
          (try (f 7) (catch E () (f 8)))))'''
        nodes, diags = read(text)
        self.assertEqual(diags, [])
        sites = tail_sites(nodes, 'f')
        self.assertEqual(len(sites), 1)
        for text in ['(lam ((x Int)) (f x))', '(g (f 1))', '(and true (f 1))',
                     '(or false (f 1))', '(Some (f 1))', '(list (f 1))']:
            nodes, _ = read(text)
            self.assertEqual(tail_sites(nodes, 'f'), set())
        lowered = lower(self.prog, ['tailcall.guarded', 'tailcall.non-tail', 'tailcall.loop'])
        self.assertFalse(lowered.fns['tailcall.guarded'].tail)
        self.assertFalse(lowered.fns['tailcall.non-tail'].tail)
        self.assertTrue(lowered.fns['tailcall.loop'].tail)
