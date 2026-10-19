"""Static acceptance validation must never evaluate a scenario."""
import json
from pathlib import Path
import tempfile
import unittest

from test_index_stdlib import run_lm as run_lm24


ACCEPT24_PROGRAM = '''(module demo
  (purpose "Static scenario validation fixture.")
  (export value effects broken)
  (error Bad (value Int))
  (fn value (purpose "Return the argument.") (sig (x Int) -> Int)
    (example (1) => 1) (body x))
  (fn effects (purpose "Declare two effects.") (sig -> Int)
    (eff io.out fs.read) (body 1))
  (fn hidden (purpose "Private function.") (sig -> Int)
    (example () => 1) (body 1))
  (fn broken (purpose "Never evaluate during validation.") (sig -> Int)
    (requires false) (example () => 1) (body 1)))
'''


class ScenarioValidationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / 'src').mkdir()
        (self.root / 'src/demo.lm').write_text(ACCEPT24_PROGRAM)
        (self.root / 'tests/accept').mkdir(parents=True)

    def scenario(self, clauses, status='proposed'):
        path = self.root / 'tests/accept/demo.accept'
        path.write_text('(scenarios\n  (scenario "Case" (status ' + status
                        + ') (why "Reason") ' + clauses + '))\n')
        return path

    def test_invalid_check(self):
        cases = [
            ('(allow a b) (run demo.value 1) (expect 1)',
             'write one effect per clause: (allow a) (allow b)'),
            ('(run demo.missing) (expect 1)', 'unknown function'),
            ('(run demo.value "bad") (expect 1)', 'type-check'),
            ('(run demo.value 1) (expect "bad")', 'type-check'),
            ('(run demo.effects) (expect 1)', 'fs.read io.out'),
            ('(allow unknown) (run demo.value 1) (expect 1)',
             'unknown effect'),
            ('(run demo.value 1) (expect-fail demo.Missing)', 'error'),
            ('(run demo.value 1) (expect-fail demo.Bad "bad")', 'type-check'),
            ('(run demo.value 1) (expect-fail Bad 1)', 'qualified'),
            ('(run demo.value 1) (expect-fail "DivZero")', 'error'),
            ('(run demo.value 1) (expect-out 1)', 'exactly one string'),
            ('(run demo.value 1) (expect-out)', 'exactly one string'),
            ('(run demo.value 1) (expect 1 2)', 'exactly one'),
            ('(why "Again") (run demo.value 1) (expect 1)', 'duplicate'),
            ('(status proposed) (run demo.value 1) (expect 1)', 'duplicate'),
            ('(allow (io.out)) (run demo.value 1) (expect 1)', 'allow'),
        ]
        for clauses, message in cases:
            with self.subTest(clauses=clauses):
                path = self.scenario(clauses)
                result = run_lm24(['check'], self.root)
                self.assertEqual(result.returncode, 1, result.stderr)
                diags = [json.loads(s) for s in result.stdout.splitlines()]
                errors = [d for d in diags if d['code'] == 'E-SCENARIO']
                self.assertEqual(len(errors), 1, result.stdout)
                diag = errors[0]
                self.assertIn(message, diag['msg'])
                self.assertEqual(diag['file'],
                                 str(path.relative_to(self.root)))
                self.assertEqual(diag['line'], 2)
                self.assertEqual(diag['path'], 'scenario:Case')
                self.assertEqual(diag['severity'], 'error')
                self.assertFalse(diag.get('fix'))
                self.assertIn('1 errors', result.stderr)

    def test_guard_shape_without_execution(self):
        self.scenario('(allow io.out fs.read) (run demo.broken) (expect 1)')
        result = run_lm24(['accept', '--guard'], self.root)
        self.assertEqual(result.returncode, 1)
        self.assertIn('INVALID   Case:', result.stdout)

    def test_no_execution_and_explicit_scope(self):
        self.scenario('(run demo.broken) (expect 1)')
        self.assertEqual(run_lm24(['check'], self.root).returncode, 0)
        self.scenario('(run demo.missing) (expect 1)')
        self.assertEqual(run_lm24(['check', 'src'], self.root).returncode, 0)

    def test_container_errors(self):
        for text in ('(', '(wrong)'):
            with self.subTest(text=text):
                path = self.scenario('(run demo.value 1) (expect 1)')
                path.write_text(text)
                result = run_lm24(['check'], self.root)
                self.assertEqual(result.returncode, 1)
                rows = map(json.loads, result.stdout.splitlines())
                diag = next(d for d in rows
                            if d['code'] == 'E-SCENARIO')
                self.assertEqual(diag['code'], 'E-SCENARIO')
                self.assertEqual(diag['file'],
                                 str(path.relative_to(self.root)))

    def test_approval_refuses_invalid_types(self):
        from lm.accept import load_scenarios

        self.scenario('(run demo.value "bad") (expect 1)')
        scenarios, _ = load_scenarios(self.root / 'tests/accept')
        result = run_lm24(['accept', '--approve', scenarios[0].digest(),
                         '--by', 'unit test'], self.root)
        self.assertEqual(result.returncode, 1)
        self.assertFalse((self.root / 'accept.lock').exists())
        self.assertIn('(status proposed)', Path(scenarios[0].file).read_text())

    def test_review_malformed_expectation(self):
        self.scenario('(run demo.value 1) (expect-out)')
        result = run_lm24(['accept', '--review'], self.root)
        self.assertEqual(result.returncode, 1)
        self.assertIn('INVALID   Case:', result.stdout)
        self.assertNotIn('Traceback', result.stderr)
