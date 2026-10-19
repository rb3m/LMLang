"""Gregorian and UTC dates: independent datetime oracle and target parity."""
import datetime as dt
from pathlib import Path
import random
import subprocess
import sys
import tempfile
import unittest

from lm.build import find_go, lower_examples, run_examples_go
from lm.check import Checker
from lm.interp import Interp
from lm.loader import load
from lm.pybackend import emit_cases
from lm.runner import example_outcomes
from lm.values import INT_MAX, INT_MIN, Rec, Var

ROOT = Path(__file__).resolve().parents[2]
EPOCH = dt.date(1970, 1, 1)
MIN_DAY, MAX_DAY = -719162, 2932896
DAY_MS = 86400000
NONE = Var('', 'None')


def some(value):
    return Var('', 'Some', (value,))


def date(year, month, day):
    return Rec('date.Date', (('year', year), ('month', month), ('day', day)))


def datetime(year, month, day, hour=0, minute=0, second=0, ms=0):
    return Rec('date.DateTime', (('date', date(year, month, day)), ('hour', hour),
                                ('minute', minute), ('second', second), ('ms', ms)))


class Date(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.prog = load([str(ROOT / 'stdlib/date.lm'),
                         str(ROOT / 'tests/spec/run/date-runtime.lm')])
        Checker(cls.prog).run()
        errors = [d.to_json() for d in cls.prog.diags if d.severity == 'error']
        if errors:
            raise AssertionError(errors)
        cls.module = cls.prog.modules['date']

    def call(self, name, *args):
        return Interp(self.prog).call_fn(self.module.fns[name], list(args))

    def test_leaps_and_invalid_records(self):
        for year, expected in [(1, False), (4, True), (1900, False), (2000, True), (2100, False)]:
            self.assertEqual(self.call('is-leap-year', year), expected)
        for y, m, d in [(0, 1, 1), (10000, 1, 1), (1900, 2, 29), (2000, 2, 30),
                        (2024, 0, 1), (2024, 13, 1), (2024, 4, 31), (2024, 1, 0),
                        (INT_MIN, INT_MAX, INT_MIN)]:
            with self.subTest(y=y, m=m, d=d):
                self.assertFalse(self.call('valid', date(y, m, d)))
                self.assertEqual(self.call('make', y, m, d), NONE)
        self.assertEqual(self.call('make', 2000, 2, 29), some(date(2000, 2, 29)))

    def test_strict_date_text(self):
        for text in ['', '0000-01-01', '10000-01-01', '1900-02-29', '2024-2-29',
                     '2024-02-9', '+024-02-29', ' 024-02-29', '2024/02/29',
                     '2024-02-29 ', '2024-02-29\n', '２０２４-02-29', '2024-٠٢-29',
                     '2024-02-²9', '2024-02-2a', '2024-02-29T00:00:00.000Z']:
            with self.subTest(text=text):
                self.assertEqual(self.call('parse', text), NONE)
        for text, fields in [('0001-01-01', (1, 1, 1)), ('9999-12-31', (9999, 12, 31)),
                             ('2000-02-29', (2000, 2, 29))]:
            self.assertEqual(self.call('parse', text), some(date(*fields)))
            self.assertEqual(self.call('print', date(*fields)), text)

    def test_day_conversion_oracle(self):
        rng = random.Random(1802)
        days = [MIN_DAY, MIN_DAY + 1, MAX_DAY - 1, MAX_DAY, -1, 0, 1,
                (dt.date(1900, 3, 1) - EPOCH).days, (dt.date(2000, 2, 29) - EPOCH).days]
        days += [rng.randint(MIN_DAY, MAX_DAY) for _ in range(160)]
        for n in days:
            expected = EPOCH + dt.timedelta(days=n)
            value = date(expected.year, expected.month, expected.day)
            with self.subTest(n=n):
                self.assertEqual(self.call('from-days', n), some(value))
                self.assertEqual(self.call('to-days', value), n)
                self.assertEqual(self.call('weekday', value), expected.isoweekday())
                self.assertEqual(self.call('add-days', value, 0), some(value))
        for n in [INT_MIN, MIN_DAY - 1, MAX_DAY + 1, INT_MAX]:
            self.assertEqual(self.call('from-days', n), NONE)

    def test_arithmetic_and_comparison(self):
        a, b = date(2000, 2, 28), date(2000, 3, 1)
        self.assertEqual(self.call('add-days', a, 1), some(date(2000, 2, 29)))
        self.assertEqual(self.call('diff-days', b, a), 2)
        for x, y, expected in [(a, b, -1), (a, a, 0), (b, a, 1)]:
            self.assertEqual(self.call('compare', x, y), expected)
        for value, n in [(date(1, 1, 1), -1), (date(9999, 12, 31), 1),
                         (date(1, 1, 1), INT_MIN), (date(9999, 12, 31), INT_MAX),
                         (date(2000, 1, 1), INT_MIN), (date(2000, 1, 1), INT_MAX)]:
            self.assertEqual(self.call('add-days', value, n), NONE)

    def test_datetime_validation(self):
        for hour, minute, second, ms in [(24, 0, 0, 0), (-1, 0, 0, 0), (0, 60, 0, 0),
                                         (0, -1, 0, 0), (0, 0, 60, 0), (0, 0, -1, 0),
                                         (0, 0, 0, -1), (0, 0, 0, 1000),
                                         (INT_MIN, INT_MAX, INT_MIN, INT_MAX)]:
            value = datetime(2000, 2, 29, hour, minute, second, ms)
            self.assertFalse(self.call('valid-datetime', value))
            self.assertEqual(self.call('make-datetime', date(2000, 2, 29), hour, minute, second, ms), NONE)
        self.assertFalse(self.call('valid-datetime', datetime(1900, 2, 29)))
        self.assertEqual(self.call('make-datetime', date(2000, 2, 29), 23, 59, 59, 999),
                         some(datetime(2000, 2, 29, 23, 59, 59, 999)))

    def test_epoch_oracle_and_bounds(self):
        low, high = MIN_DAY * DAY_MS, (MAX_DAY + 1) * DAY_MS - 1
        rng = random.Random(1803)
        times = [low, low + 1, high - 1, high, -DAY_MS - 1, -DAY_MS, -1001, -1000,
                 -999, -1, 0, 1, 999, 1000, DAY_MS]
        times += [rng.randint(low, high) for _ in range(100)]
        for n in times:
            days, rem = divmod(n, DAY_MS)
            civil = EPOCH + dt.timedelta(days=days)
            hour, rem = divmod(rem, 3600000)
            minute, rem = divmod(rem, 60000)
            second, ms = divmod(rem, 1000)
            value = datetime(civil.year, civil.month, civil.day, hour, minute, second, ms)
            text = (f'{civil.year:04d}-{civil.month:02d}-{civil.day:02d}'
                    f'T{hour:02d}:{minute:02d}:{second:02d}.{ms:03d}Z')
            with self.subTest(n=n):
                self.assertEqual(self.call('from-epoch-ms', n), some(value))
                self.assertEqual(self.call('to-epoch-ms', value), n)
                self.assertEqual(self.call('print-datetime', value), text)
                self.assertEqual(self.call('parse-datetime', text), some(value))
        for n in [INT_MIN, low - 1, high + 1, INT_MAX]:
            self.assertEqual(self.call('from-epoch-ms', n), NONE)

    def test_strict_datetime_and_compare(self):
        for text in ['', '0000-01-01T00:00:00.000Z', '1900-02-29T00:00:00.000Z',
                     '2000-02-29T24:00:00.000Z', '2000-02-29T00:60:00.000Z',
                     '2000-02-29T00:00:60.000Z', '2000-02-29T00:00:00.00Z',
                     '2000-02-29T00:00:00.0000Z', '2000-02-29t00:00:00.000Z',
                     '2000-02-29T00:00:00.000z', '2000-02-29 00:00:00.000Z',
                     '2000-02-29T00:00:00.000+00:00', '2000-02-29T00:00:00.000Z\n',
                     '2000-02-29T٠٠:00:00.000Z', '2000-02-29T00:00:00,000Z',
                     '2000-02-29T00:00:00. 00Z']:
            with self.subTest(text=text):
                self.assertEqual(self.call('parse-datetime', text), NONE)
        a, b = datetime(1969, 12, 31, 23, 59, 59, 999), datetime(1970, 1, 1)
        for x, y, expected in [(a, b, -1), (a, a, 0), (b, a, 1)]:
            self.assertEqual(self.call('compare-datetime', x, y), expected)

    def test_python_target_parity(self):
        want = example_outcomes(self.prog, ['date', 'date-runtime'])
        lowered, cases = lower_examples(self.prog, ['date', 'date-runtime'])
        self.assertTrue(cases)
        with tempfile.TemporaryDirectory(prefix='lm-date-py-') as tmp:
            script = Path(tmp) / 'cases.py'
            script.write_text(emit_cases(lowered, cases))
            result = subprocess.run([sys.executable, str(script)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        actual = {}
        for line in result.stdout.splitlines():
            name, kind, value = line.split('\t', 2)
            actual[name] = (kind, value)
        self.assertEqual(actual, want)

    def test_go_target_parity(self):
        if find_go() is None:
            sys.stderr.write('\nSKIP: Go toolchain missing; date differential not run\n')
            self.skipTest('Go toolchain missing')
        self.assertEqual(run_examples_go(self.prog, ['date', 'date-runtime']),
                         example_outcomes(self.prog, ['date', 'date-runtime']))
