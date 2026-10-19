import unittest
from pathlib import Path

from lm.sexpr import read, to_data


class ReaderTests(unittest.TestCase):
    def ok(self, text):
        node, diags = read(text)
        self.assertEqual(diags, [], diags)
        return to_data(node)

    def code(self, text):
        node, diags = read(text)
        self.assertIsNone(node)
        return diags[0]

    def test_atoms(self):
        self.assertEqual(self.ok('(a 1 -2 "s" B m.x m.T + -> => _)'),
                         (("sym", "a"), ("int", 1), ("int", -2), ("str", "s"), ("type", "B"),
                          ("sym", "m.x"), ("type", "m.T"), ("sym", "+"), ("sym", "->"), ("sym", "=>"), ("sym", "_")))

    def test_minus_is_symbol_alone_int_with_digits(self):
        self.assertEqual(self.ok("(- -1 1)"), (("sym", "-"), ("int", -1), ("int", 1)))

    def test_string_escapes(self):
        self.assertEqual(self.ok(r'("a\"b\\c\nd\te")'), (("str", 'a"b\\c\nd\te'),))

    def test_positions(self):
        node, _ = read("(a\n  (b))")
        inner = node.items[1]
        self.assertEqual((inner.line, inner.col), (2, 3))

    def test_errors(self):
        self.assertEqual(self.code("(a").msg, "unclosed `(`")
        self.assertEqual(self.code("a)").code, "E-PARSE")
        self.assertEqual(self.code(")").msg, "unexpected `)`")
        self.assertIn("invalid token", self.code("(1abc)").msg)
        self.assertIn("invalid token", self.code("(Foo_bar)").msg)
        self.assertIn("unterminated", self.code('("abc)').msg)
        self.assertIn("invalid escape", self.code(r'("a\q")').msg)
        self.assertIn("exactly one", self.code("(a) (b)").msg)
        self.assertIn("exactly one", self.code("").msg)
        self.assertIn("control character", self.code('("a\tb")').msg)

    def test_error_position(self):
        d = self.code("(a\n (b ?x))")
        self.assertEqual((d.line, d.col), (2, 5))

    def test_diagnostic_position_fixtures(self):
        fixtures = Path(__file__).resolve().parents[1] / "spec/diag"
        for expected in sorted(fixtures.glob("*.position")):
            with self.subTest(fixture=expected.stem):
                d = self.code(expected.with_suffix(".lm").read_text())
                self.assertEqual(d.code, "E-PARSE")
                self.assertEqual((d.line, d.col), tuple(map(int, expected.read_text().split())))

    def test_indentation_does_not_reject_balanced_forms(self):
        self.ok("(a\n(b)\n(c))")

    def test_unicode_escapes(self):
        node, diags = read(r'("\u{0}\u{41}\u{10ffff}\u{1f600}\u{0041}")')
        self.assertEqual(diags, [])
        self.assertEqual(node.items[0].value, "\x00A\U0010ffff\U0001f600A")

        # Error cases
        self.assertIn("cannot be a surrogate", self.code(r'("\u{d800}")').msg)
        self.assertIn("cannot be a surrogate", self.code(r'("\u{dfff}")').msg)
        self.assertIn("out of range", self.code(r'("\u{110000}")').msg)
        self.assertIn("too large", self.code(r'("\u{0000041}")').msg)
        self.assertIn("empty unicode escape", self.code(r'("\u{}")').msg)
        self.assertIn("invalid hex digit", self.code(r'("\u{12g4}")').msg)
        self.assertIn("invalid escape", self.code(r'("\u0041")').msg)
        self.assertIn("unterminated unicode escape", self.code(r'("\u{41")').msg)

    def test_no_comments(self):
        self.assertEqual(self.code("(a ; c\n)").code, "E-PARSE")


if __name__ == "__main__":
    unittest.main()
