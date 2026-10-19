import random
import unittest
from pathlib import Path

from lm.ast import canonicalize
from lm.printer import WIDTH, format_text
from lm.sexpr import Atom, read, to_data

ROOT = Path(__file__).resolve().parents[2]


def codes(text, check=False):
    out, diags = format_text(text)
    return out, sorted({d.code for d in diags})


class FormatTests(unittest.TestCase):
    def test_canonical_order_and_spacing(self):
        out, c = codes('(module m (fn b (body 1)) (fn a (body 2)) (purpose "p") (use z a))')
        self.assertEqual(c, [])
        self.assertEqual(out, '(module m\n  (purpose "p")\n  (use a z)\n  (fn a\n    (body 2))\n  (fn b\n    (body 1)))\n')

    def test_empty_clauses_dropped(self):
        out, _ = codes('(module m (use) (fn a (eff) (fails) (body 1)))')
        self.assertEqual(out, "(module m\n  (fn a\n    (body 1)))\n")

    def test_empty_export_kept(self):
        out, _ = codes('(module m (export) (fn a (body 1)))')
        self.assertEqual(out, "(module m\n  (export)\n  (fn a\n    (body 1)))\n")

    def test_module_without_clauses(self):
        self.assertEqual(codes("(module m)")[0], "(module m)\n")

    def test_line_breaking(self):
        long = "(body (f " + " ".join(f"arg{i:03d}" for i in range(30)) + "))"
        out, _ = codes(f"(module m (fn a {long}))")
        self.assertTrue(all(len(l) <= WIDTH for l in out.splitlines()), out)
        self.assertIn("(body (f\n", out.replace("(body\n      (f", "(body (f\n"))

    def test_string_escaping_round_trip(self):
        out, _ = codes(r'(module m (fn a (body "q\"b\\n\n\t")))')
        self.assertIn(r'"q\"b\\n\n\t"', out)

    def test_int_normalization(self):
        out, _ = codes("(module m (fn a (body (+ 007 -0))))")
        self.assertIn("(+ 7 0)", out)

    def test_dup_names_rejected(self):
        self.assertEqual(codes("(module m (fn a (body 1)) (fn a (body 2)))")[1], ["E-DUP-NAME"])
        self.assertEqual(codes("(module m (use a a))")[1], ["E-DUP-NAME"])
        self.assertEqual(codes("(module m (fn a (eff io.out io.out)))")[1], ["E-DUP-NAME"])

    def test_structure_errors(self):
        for src in ["(foo)", "(module)", "(module M)", "(module m (zzz))", '(module m (purpose "a") (purpose "b"))',
                    "(module m (purpose 1))", "(module m (fn A))", "(module m (fn a (nope)))",
                    "(module m (fn a (body 1) (body 2)))", "(module m (use Foo))", "(module m (type lower Int))"]:
            self.assertEqual(codes(src)[1], ["E-PARSE"], src)

    def test_fixtures_fmt(self):
        for inp in sorted((ROOT / "tests/spec/fmt").glob("*.in.lm")):
            want = inp.with_name(inp.name.replace(".in.", ".out.")).read_text()
            got, c = codes(inp.read_text())
            self.assertEqual(c, [], inp.name)
            self.assertEqual(got, want, inp.name)
            self.assertEqual(codes(want)[0], want, f"{inp.name}: output not a fixed point")

    def test_fixtures_diag(self):
        for src in sorted((ROOT / "tests/spec/diag").glob("*.lm")):
            want = sorted(src.with_suffix(".expect").read_text().split())
            out, c = codes(src.read_text())
            if want == ["E-NONCANONICAL"]:
                self.assertIsNotNone(out, src.name)
                self.assertNotEqual(out, src.read_text(), src.name)
            else:
                self.assertEqual(c, want, src.name)


# ---- property test: random programs ---------------------------------------------------------

SYMS = ["x", "y-z", "list.map", "+", "-", "io.out", "_", "true", "=", "->", "mod"]
TYPES = ["Int", "List", "Cents", "m.Item", "Some"]
STRS = ["", "a b", 'q"uote', "back\\slash", "tab\there", "nl\nx", "long" * 30]


def rexpr(r, depth=0):
    k = r.random()
    if depth > 3 or k < 0.35:
        c = r.random()
        if c < 0.3:
            return str(r.randint(-999, 999))
        if c < 0.5:
            return _q(r.choice(STRS))
        if c < 0.8:
            return r.choice(SYMS)
        return r.choice(TYPES)
    return "(" + _sep(r).join(rexpr(r, depth + 1) for _ in range(r.randint(1, 7))) + ")"


def _q(s):
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\t", "\\t") + '"'


def _sep(r):
    return r.choice([" ", "  ", "\n", "\n  ", "\t"])


def rprog(r):
    fns = []
    for i in r.sample(range(1, 40), r.randint(0, 5)):
        cl = [f"(purpose {_q(r.choice(STRS))})", f"(sig {rexpr(r)} -> {rexpr(r)})", f"(body {rexpr(r)})"]
        cl += [f"(requires {rexpr(r)})" for _ in range(r.randint(0, 2))]
        cl += [f"(ensures {rexpr(r)})" for _ in range(r.randint(0, 2))]
        cl += [f"(example ({rexpr(r)}) => {rexpr(r)})" for _ in range(r.randint(0, 3))]
        if r.random() < 0.5:
            cl.append("(eff " + " ".join(r.sample(["io.out", "io.in", "fs.read", "rand"], r.randint(1, 3))) + ")")
        if r.random() < 0.5:
            cl.append("(fails " + " ".join(r.sample(["DivZero", "OutOfRange", "m.Bad"], r.randint(1, 3))) + ")")
        r.shuffle(cl)
        fns.append(f"(fn f{i}" + _sep(r) + _sep(r).join(cl) + ")")
    top = [f"(purpose {_q('p')})"] + fns
    if r.random() < 0.7:
        top.append("(use " + " ".join(r.sample(["list", "str", "math", "io"], r.randint(1, 4))) + ")")
    if r.random() < 0.7:
        top.append("(export " + " ".join(r.sample(["a", "b", "c"], r.randint(1, 3))) + ")")
    for i in r.sample(range(1, 20), r.randint(0, 3)):
        top.append(f"(type T{i} {rexpr(r)})")
        top.append(f"(error E{i} {rexpr(r)})")
    r.shuffle(top)
    return "(module m" + _sep(r) + _sep(r).join(top) + ")"


def atoms(node):
    if isinstance(node, Atom):
        return [(node.kind, node.value)]
    return [a for i in node.items for a in atoms(i)]


class PropertyTests(unittest.TestCase):
    def test_random_programs(self):
        r = random.Random(20261015)
        for n in range(400):
            src = rprog(r)
            out, d = format_text(src)
            self.assertIsNotNone(out, (src, [x.to_json() for x in d]))
            # idempotent
            self.assertEqual(format_text(out)[0], out, src)
            # no line exceeds width unless a single token forces it
            for line in out.splitlines():
                body = line.rstrip(")")  # ancestors' closing parens are not counted (SPEC rule 3)
                if len(body) > WIDTH:
                    self.assertNotIn(" ", body.strip().strip("("), (line,))
            # meaning preserved: same atoms (multiset) and same canonical tree
            a_in = sorted(map(repr, atoms(read(src)[0])))
            a_out = sorted(map(repr, atoms(read(out)[0])))
            self.assertEqual(a_in, a_out, src)
            c_in = canonicalize(read(src)[0])[0]
            c_out = canonicalize(read(out)[0])[0]
            self.assertEqual(to_data(c_in), to_data(c_out), src)


if __name__ == "__main__":
    unittest.main()
