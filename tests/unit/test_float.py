"""Float (ADR-039): literal grammar, canonical text, and Go runtime parity with Python on random inputs.

The parity tests compile a small harness against lm/runtime/go and compare, line by line, Go's
canonical text, `str.to-float` and checked arithmetic with the interpreter's. They SKIP visibly
without Go (see test_gobackend.need_go).
"""
import math
import random
import shutil
import struct
import subprocess
import tempfile
import unittest
from pathlib import Path

from lm import gobackend
from lm.build import GO_MOD, find_go, go_build
from lm.float_prims import to_float
from lm.interp import PRELUDE_FNS
from lm.printer import float_text, format_text
from lm.sexpr import read, to_data
from lm.values import FloatFault, show


def need_go():
    if find_go() is None:
        import sys
        sys.stderr.write("\nSKIP: Go toolchain not found (PATH or LM_GO); Float parity tests NOT run\n")
        raise unittest.SkipTest("go not found: Float parity tests not run")

HARNESS = r'''package main

import (
	"bufio"
	"math"
	"os"
	"strconv"
	"strings"
)

// Reads `show HEX`, `parse TEXT` or `OP HEX HEX` lines; prints one result line each.
func main() {
	in := bufio.NewScanner(os.Stdin)
	in.Buffer(make([]byte, 1<<20), 1<<20)
	bits := func(h string) float64 { u, _ := strconv.ParseUint(h, 16, 64); return math.Float64frombits(u) }
	for in.Scan() {
		f := strings.SplitN(in.Text(), " ", 3)
		switch f[0] {
		case "show":
			writeLine(showFloat(bits(f[1])))
		case "parse":
			writeLine(show(prim_str_to_float(strings.TrimPrefix(in.Text(), "parse "))))
		default:
			kind, v, _, ft := outcome(func() Value { return farith(f[0], bits(f[1]), bits(f[2]), -1) })
			if kind == "fault" {
				writeLine(ft.D.Code)
			} else {
				writeLine(show(v))
			}
		}
	}
	out.Flush()
}
'''


def hexbits(x: float) -> str:
    return f"{struct.unpack('<Q', struct.pack('<d', x))[0]:016x}"


def random_floats(rng, n):
    """Uniform bit patterns (all exponents, subnormals) plus short decimals; finite, no -0.0."""
    out = [0.0, 5e-324, 2.2250738585072014e-308, 1.7976931348623157e+308, 0.1, 100.0, 1e16, 1e-05,
           0.0001, 9999999999999998.0, 1e22, 1.5e300, 123456789.123, 2.0 ** 63, 2.0 ** 53 + 2]
    while len(out) < n:
        x = struct.unpack("<d", struct.pack("<Q", rng.getrandbits(64)))[0]
        if rng.random() < 0.4:
            x = float(f"{rng.randint(-10**6, 10**6)}e{rng.randint(-25, 25)}")
        if math.isfinite(x):
            out.append(x + 0.0)
    return out + [-x for x in out if x]


def random_texts(rng, n):
    fixed = ["1.", ".5", "+1", "-0", "1e400", "-1e-400", "1_0", "0x10", "inf", "nan", "", "1e", ". ", "1.5 ",
             "1.7976931348623157e308", "1.7976931348623158e308", "1.7976931348623159e308",
             "4.9406564584124654e-324", "2.4703282292062327e-324", "2.4703282292062328e-324",
             "9007199254740993", "0." + "0" * 400 + "1", "1" * 400, "1e99999999999999999999"]
    pieces = ["", "+", "-", "0", "1", "9", ".", "e", "E", "5", "e-", "e+3", "00", "7.25", "e308", "e-320"]
    out = fixed + [repr(x) for x in random_floats(rng, n // 2)]
    while len(out) < n:
        out.append("".join(rng.choice(pieces) for _ in range(rng.randint(1, 6))))
    return out


class LiteralsAndText(unittest.TestCase):
    def test_reader_grammar(self):
        node, d = read("(1.0 -0.5 2.5e-3 1e+16 1E5 -0.0 7)")
        self.assertEqual(d, [])
        self.assertEqual(to_data(node), (("float", 1.0), ("float", -0.5), ("float", 0.0025), ("float", 1e16),
                                         ("float", 1e5), ("float", 0.0), ("int", 7)))
        self.assertEqual(math.copysign(1, node.items[5].value), 1.0)  # -0.0 is normalized on reading
        for bad in ("1.", ".5", "1e", "1.e5", "1_0.0", "0x1p3", "1.5f"):  # `inf`, `nan` are just names
            self.assertIsNone(read(f"({bad})")[0], bad)

    def test_canonical_text_is_python_repr(self):
        cases = {100.0: "100.0", 0.0001: "0.0001", 1e-05: "1e-05", 1e16: "1e+16", 1.5e300: "1.5e+300",
                 0.1 + 0.2: "0.30000000000000004", -0.0: "0.0", 1e15: "1000000000000000.0"}
        for x, text in cases.items():
            self.assertEqual(float_text(x), text)
            self.assertEqual(show(x), text)

    def test_nonfinite_literal_keeps_its_text(self):
        src = '(module m\n  (purpose "p")\n  (fn f\n    (purpose "p")\n    (sig -> Float)\n    (body 1e400)))\n'
        self.assertEqual(format_text(src)[0], src)

    def test_interpreter_faults_and_normalizes(self):
        with self.assertRaises(FloatFault):
            PRELUDE_FNS["/"](1.0, 0.0)
        with self.assertRaises(FloatFault):
            PRELUDE_FNS["*"](1e300, 1e300)
        self.assertEqual(show(PRELUDE_FNS["*"](-1.0, 0.0)), "0.0")


class GoParity(unittest.TestCase):
    """Go runtime vs interpreter on random inputs: canonical text, str.to-float, + - * /."""

    @classmethod
    def setUpClass(cls):
        need_go()
        cls.tmp = tempfile.mkdtemp(prefix="lm-float-")
        d = Path(cls.tmp)
        for f in gobackend.RUNTIME.glob("*.go"):
            shutil.copyfile(f, d / f"lm_{f.name}")
        (d / "main.go").write_text(HARNESS, encoding="utf-8")
        (d / "go.mod").write_text(GO_MOD, encoding="utf-8")
        cls.exe = d / "harness"
        go_build(find_go(), d, cls.exe)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def run_go(self, lines):
        p = subprocess.run([str(self.exe)], input="\n".join(lines) + "\n", capture_output=True, text=True, check=True)
        return p.stdout.splitlines()

    def compare(self, lines, want):
        got = self.run_go(lines)
        diffs = [f"{q}: python {w!r} go {g!r}" for q, w, g in zip(lines, want, got) if w != g]
        self.assertEqual(len(got), len(want))
        self.assertEqual(diffs[:10], [])

    def test_canonical_text(self):
        xs = random_floats(random.Random(39), 20000)
        self.compare([f"show {hexbits(x)}" for x in xs], [repr(x) for x in xs])

    def test_to_float(self):
        texts = random_texts(random.Random(40), 6000)
        self.compare([f"parse {t}" for t in texts], [show(to_float(None, t)) for t in texts])

    def test_arithmetic(self):
        rng = random.Random(41)
        xs = random_floats(rng, 4000)
        lines, want = [], []
        for op in "+-*/":
            for _ in range(3000):
                a, b = rng.choice(xs), rng.choice(xs + [0.0, 1.0, 2.0])
                lines.append(f"{op} {hexbits(a)} {hexbits(b)}")
                try:
                    want.append(show(PRELUDE_FNS[op](a, b)))
                except FloatFault:
                    want.append("E-FLOAT")
        self.compare(lines, want)
