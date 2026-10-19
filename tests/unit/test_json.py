"""Strict JSON diagnostics, pinned independently and compared with a compiled harness."""
import subprocess
import tempfile
import unittest
from pathlib import Path

from lm.check import Checker
from lm.interp import Interp
from lm.loader import load
from lm.values import LmFail, Named
from test_gobackend import need_go, lm

# Every position is a code-point offset, including EOF. No host parser supplies expectations.
MALFORMED = [
    ('', 0, 'unexpected end'), (' ', 1, 'unexpected end'),
    ('x', 0, 'unexpected character'), ('NaN', 0, 'unexpected character'),
    ('Infinity', 0, 'unexpected character'), ('-Infinity', 1, 'unexpected character'),
    ('+1', 0, 'unexpected character'), ('.1', 0, 'unexpected character'),
    ('[', 1, 'unexpected end'), ('{', 1, 'unexpected end'),
    ('[1,]', 3, 'unexpected character'), ('{"a":}', 5, 'unexpected character'),
    ('{"a" 1}', 5, 'unexpected character'), ('{a:1}', 1, 'unexpected character'),
    ('{"a":1,}', 7, 'unexpected character'), ('[1 2]', 3, 'unexpected character'),
    ('[true', 5, 'unexpected end'), ('tru', 3, 'unexpected end'),
    ('trux', 3, 'unexpected character'), ('False', 0, 'unexpected character'),
    ('01', 1, 'trailing data'), ('-01', 2, 'trailing data'),
    ('1.', 2, 'unexpected end'), ('1.e2', 2, 'unexpected character'),
    ('1e', 2, 'unexpected end'), ('1e+', 3, 'unexpected end'),
    ('1e-x', 3, 'unexpected character'), ('-', 1, 'unexpected end'),
    ('1e400', 5, 'number out of range'), ('-1e400', 6, 'number out of range'),
    ('null false', 5, 'trailing data'), ('"é🚀" x', 5, 'trailing data'),
    ('\u00a0null', 0, 'unexpected character'), ('"abc', 4, 'unexpected end'),
    ('"\\', 2, 'unexpected end'), ('"\\x"', 2, 'bad escape'),
    ('"\\u12z4"', 5, 'bad escape'), ('"\\u12', 5, 'unexpected end'),
    ('"a\n"', 2, 'control character in string'), ('"\x00"', 1, 'control character in string'),
    ('"\\ud800"', 7, 'unpaired surrogate'), ('"\\udc00"', 7, 'unpaired surrogate'),
    ('"\\ud800\\u0041"', 13, 'unpaired surrogate'),
    ('{"a":1,"\\u0061":2}', 15, 'duplicate key'),
    ('{"é":0,"é":1}', 10, 'duplicate key'),
    ('[1,,2]', 3, 'unexpected character'), ('{}x', 2, 'trailing data'),
]


class StrictJson(unittest.TestCase):
    def test_malformed_positions_identical_in_built_binary(self):
        need_go()
        prog = load(['stdlib/json.lm'])
        Checker(prog).run()
        self.assertEqual([d.to_json() for d in prog.diags if d.severity == 'error'], [])
        parse_fn = Named(prog.modules['json'].fns['parse'])
        print_fn = Named(prog.modules['json'].fns['print'])

        def parse(text):
            return Interp(prog).apply(parse_fn, [text])

        def render(value):
            return Interp(prog).apply(print_fn, [value])
        for s, pos, msg in MALFORMED:
            with self.subTest(s=s):
                with self.assertRaises(LmFail) as fail:
                    parse(s)
                self.assertEqual((fail.exception.id, fail.exception.args_), ('json.BadJson', (pos, msg)))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'json-invalid.lm'
            path.write_text('''(module json-invalid
              (purpose "Pin malformed JSON diagnostics through a built binary.")
              (use json io str)
              (fn main
                (purpose "Print the position and message of a JSON parse failure.")
                (sig -> Unit) (eff io.in io.out) (fails io.IoError)
                (body (try (io.print (json.print (json.parse (io.read-all))))
                  (catch json.BadJson (pos msg)
                    (do (io.print (str.from-int pos)) (io.print msg)))))))''')
            exe = Path(tmp) / 'invalid'
            rc, out, err = lm('build', 'json-invalid.main', str(path), '-o', str(exe))
            self.assertEqual(rc, 0, out + err)
            for s, pos, msg in MALFORMED:
                with self.subTest(s=s):
                    p = subprocess.run([str(exe)], input=s.encode(), capture_output=True)
                    self.assertEqual((p.returncode, p.stdout.decode(), p.stderr),
                                     (0, f'{pos}\n{msg}\n', b''))
            valid = [
                (' \t\r\n [null] \r\n', '[null]'),
                ('"\\\"\\\\\\/\\b\\f\\n\\r\\t\\u0000"',
                 '"\\\"\\\\/\\b\\f\\n\\r\\t\\u0000"'),
                ('"\\uD800\\uDC00"', '"𐀀"'),
                ('"\\uDBFF\\uDFFF"', '"􏿿"'),
                ('-0e100', '0.0'),
                ('1.7976931348623157e308', '1.7976931348623157e+308'),
                ('5e-324', '5e-324'),
                ('[' * 2000 + '0' + ']' * 2000, '[' * 2000 + '0' + ']' * 2000),
            ]
            for text, expected in valid:
                with self.subTest(text=text[:80]):
                    self.assertEqual(render(parse(text)), expected)
                    p = subprocess.run([str(exe)], input=text.encode(), capture_output=True)
                    self.assertEqual((p.returncode, p.stdout.decode(), p.stderr),
                                     (0, expected + '\n', b''))
