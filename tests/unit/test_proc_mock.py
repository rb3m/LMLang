"""Subprocess scripts are ordered, hermetic, and round-trip through tools."""
import unittest
from pathlib import Path
from unittest.mock import patch

from lm.check import Checker
from lm.explain import explain
from lm.fake_world import FakeWorld
from lm.index import Index
from lm.loader import load
from lm.lower import lower_examples
from lm.printer import flat, format_text
from lm.proc_examples import CATEGORIES, ProcEntry, ProcMismatch
from lm.runner import example_outcomes, test_program
from lm.sexpr import read
from lm.values import LmFail, Pair, Rec, Var

ROOT = Path(__file__).resolve().parents[2]
RUN = ROOT / 'tests/spec/run'
NONE = Var('', 'None')
RESULT = Rec('proc.Result', (('exit', Var('proc', 'Exited', (0,))),
                            ('stdout', ''), ('stderr', '')))


def checked(name):
    prog = load([str(RUN / name)])
    Checker(prog).run()
    errors = [d.to_json() for d in prog.diags if d.severity == 'error']
    if errors:
        raise AssertionError(errors)
    return prog


class ProcMockTests(unittest.TestCase):
    def test_outcomes_never_spawn(self):
        denied = AssertionError('host spawn')
        with patch('subprocess.Popen', side_effect=denied):
            diags, stats = test_program(checked('mock-proc.lm'))
            fs_diags, fs_stats = test_program(checked('mock-proc-which.lm'))
        self.assertEqual([d.to_json() for d in diags + fs_diags], [])
        self.assertEqual(stats['examples'], 6)
        self.assertEqual(fs_stats['examples'], 4)

    def test_every_mock_error_category(self):
        for category in CATEGORIES:
            with self.subTest(category=category):
                entry = ProcEntry(('/bin/x',), '', NONE, (), category)
                world = FakeWorld([('proc', (entry,))])
                with self.assertRaises(LmFail) as failure:
                    world._proc(('/bin/x',), '', NONE, ())
                self.assertEqual(failure.exception.id, 'proc.ProcError')
                self.assertEqual(failure.exception.args_, (category,))
                world.check_procs()

    def test_validation_precedes_script_matching_and_consumption(self):
        entry = ProcEntry(('/bin/x',), '', NONE, (), RESULT)
        world = FakeWorld([('proc', (entry,))])
        for argv, stdin, cwd, env in (
                ((), '', NONE, ()),
                (('relative',), '', NONE, ()),
                (('/bin/x',), '\0', NONE, ()),
                (('/bin/x',), '', NONE, (Pair('', 'x'),)),
                (('/bin/x',), '', NONE, (Pair('K', '1'), Pair('K', '2')))):
            with self.assertRaises(LmFail) as failure:
                world._proc(argv, stdin, cwd, env)
            self.assertEqual(failure.exception.args_, ('invalid-request',))
            self.assertEqual(world.proc_index, 0)
        self.assertEqual(world._proc(('/bin/x',), '', NONE, ()), RESULT)
        world.check_procs()

    def test_mismatch_and_leftovers_name_one_based_call_index(self):
        for suffix, index in (('mismatch', 1), ('missing', 1), ('leftover', 2),
                              ('env-order', 1), ('cwd-mismatch', 1)):
            with self.subTest(suffix=suffix):
                diags, stats = test_program(checked(f'mock-proc-{suffix}.lm'))
                self.assertEqual(stats['failed'], 1)
                self.assertEqual(diags[0].code, 'E-EXAMPLE-FAILED')
                self.assertIn(f'call index {index}', diags[0].msg)

    def test_mismatch_cannot_be_caught_as_proc_error(self):
        world = FakeWorld()
        with self.assertRaises(ProcMismatch):
            world._proc(('/bin/x',), '', NONE, ())

    def test_compiled_enumeration_skips_mock_examples(self):
        prog = checked('mock-proc.lm')
        self.assertEqual(lower_examples(prog, prog.targets)[1], [])
        self.assertEqual(example_outcomes(prog, prog.targets), {})

    def test_fmt_slice_explain_round_trip(self):
        prog = checked('mock-proc.lm')
        source = (RUN / 'mock-proc.lm').read_text(encoding='utf-8')
        canonical, diags = format_text(source)
        self.assertEqual(diags, [])
        self.assertEqual(format_text(canonical), (canonical, []))
        index = Index(prog)
        fn = prog.modules['mock-proc'].fns['invoke']
        example = flat(fn.clauses['example'][3])
        self.assertIn(example, flat(read(canonical)[0]))
        sliced = index.slice(fn.qual)[0]
        self.assertIn(example, ' '.join(sliced.split()))
        self.assertIn('(env "B" "2") (env "A" "1")', explain(prog, index, fn))


if __name__ == '__main__':
    unittest.main()
