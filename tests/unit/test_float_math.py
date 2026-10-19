"""ADR-057: independent high-precision accuracy evidence and exact Go/Python parity."""
import json
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
from lm.float_prims import FLOAT_PRIMS
from lm.values import FloatFault

VECTORS = json.loads((Path(__file__).parent / "data/float_math_vectors.json").read_text())["vectors"]


def hexbits(x):
    return struct.pack(">d", x).hex()


def ordered_bits(x):
    bits = int(hexbits(x), 16)
    return (~bits & ((1 << 64) - 1)) if bits >> 63 else bits | (1 << 63)


def result(op, *args):
    try:
        return hexbits(FLOAT_PRIMS["float." + op](None, *args))
    except FloatFault:
        return "E-FLOAT"


def vector_args(row):
    encoded = row["input"]
    return tuple(float.fromhex(x) for x in (encoded if isinstance(encoded, list) else [encoded]))


class FloatMathAccuracy(unittest.TestCase):
    def test_decimal_vectors(self):
        for op, rows in VECTORS.items():
            worst = 0
            for row in rows:
                args = vector_args(row)
                with self.subTest(op=op, args=args):
                    if row["expected"] == "E-FLOAT":
                        self.assertEqual(result(op, *args), "E-FLOAT")
                        continue
                    expected = float.fromhex(row["expected"])
                    actual = FLOAT_PRIMS["float." + op](None, *args)
                    self.assertTrue(math.isfinite(actual))
                    error = abs(ordered_bits(actual) - ordered_bits(expected))
                    worst = max(worst, error)
                    self.assertLessEqual(error, 1, f"{op}{args}: {actual.hex()} vs {expected.hex()}")
            print(f"\nfloat.{op}: max ulp error = {worst} ({len(rows)} Decimal vectors)", flush=True)

    def test_constants(self):
        self.assertEqual(result("pi"), "400921fb54442d18")
        self.assertEqual(result("e"), "4005bf0a8b145769")

    def test_hyperbolic_exact_facts_and_domains(self):
        for op in ("sinh", "cosh", "tanh"):
            for zero in (0.0, -0.0):
                self.assertEqual(result(op, zero), hexbits(1.0 if op == "cosh" else 0.0))
            for x in (math.inf, -math.inf, math.nan):
                with self.assertRaises(FloatFault) as caught:
                    FLOAT_PRIMS["float." + op](None, x)
                self.assertEqual(caught.exception.op, "float." + op)
            # Check bit-exact odd/even symmetry across every finite vector.
            for row in VECTORS[op]:
                x = abs(vector_args(row)[0])
                if x == 0 or row["expected"] == "E-FLOAT":
                    continue
                positive = FLOAT_PRIMS["float." + op](None, x)
                self.assertEqual(result(op, -x), hexbits(positive if op == "cosh" else -positive))
        for op in ("sinh", "tanh"):
            for tiny in (1e-300, -1e-300, 5e-324, -5e-324):
                self.assertEqual(result(op, tiny), hexbits(tiny))
        for x in (30.0, 1e300, 1.7976931348623157e308):
            for sign in (1.0, -1.0):
                self.assertEqual(result("tanh", sign * x), hexbits(sign))
        last_finite = 710.4758600739439
        for op in ("sinh", "cosh"):
            for sign in (1.0, -1.0):
                for x in (709.782712893384, 710.0,
                          math.nextafter(last_finite, 0.0), last_finite):
                    self.assertTrue(math.isfinite(FLOAT_PRIMS["float." + op](None, sign * x)))
                for x in (math.nextafter(last_finite, math.inf), 711.0,
                          1.7976931348623157e308):
                    with self.assertRaises(FloatFault) as caught:
                        FLOAT_PRIMS["float." + op](None, sign * x)
                    self.assertEqual(caught.exception.op, "float." + op)

    def test_log1p_expm1_exact_facts_and_domains(self):
        for op in ("log1p", "expm1"):
            for zero in (0.0, -0.0):
                self.assertEqual(result(op, zero), hexbits(0.0))
            for tiny in (1e-300, -1e-300, 5e-324, -5e-324):
                self.assertEqual(result(op, tiny), hexbits(tiny))
            invalid = [math.inf, -math.inf, math.nan]
            invalid += ([-1.0, math.nextafter(-1.0, -math.inf), -2.0,
                         -1.7976931348623157e308] if op == "log1p" else
                        [math.nextafter(709.782712893384, math.inf), 710.0,
                         1.7976931348623157e308])
            for x in invalid:
                with self.subTest(op=op, x=x):
                    with self.assertRaises(FloatFault) as caught:
                        FLOAT_PRIMS["float." + op](None, x)
                    self.assertEqual(caught.exception.op, "float." + op)
        self.assertEqual(result("log1p", 1.0), result("ln", 2.0))
        for x in (-1000.0, -1.7976931348623157e308):
            self.assertEqual(result("expm1", x), hexbits(-1.0))
        for op, x in [("log1p", math.nextafter(-1.0, 0.0)),
                      ("log1p", 1.7976931348623157e308),
                      ("expm1", 709.782712893384)]:
            self.assertTrue(math.isfinite(FLOAT_PRIMS["float." + op](None, x)))

    def test_trig_exact_facts_and_finite_domain(self):
        for x in (0.0, -0.0):
            self.assertEqual(result("sin", x), hexbits(0.0))
            self.assertEqual(result("cos", x), hexbits(1.0))
            self.assertEqual(result("tan", x), hexbits(0.0))
        pi = FLOAT_PRIMS["float.pi"](None)
        self.assertEqual(result("sin", pi), hexbits(1.2246467991473532e-16))
        for op in ("sin", "cos", "tan"):
            for magnitude in (5e-324, 1e22, 1e300, 1.7976931348623157e308):
                for x in (magnitude, -magnitude):
                    self.assertTrue(math.isfinite(FLOAT_PRIMS["float." + op](None, x)))
            for x in (math.inf, -math.inf, math.nan):
                with self.assertRaises(FloatFault) as caught:
                    FLOAT_PRIMS["float." + op](None, x)
                self.assertEqual(caught.exception.op, "float." + op)

    def test_domains_and_zero_normalization(self):
        for op in ("ln", "log2", "log10"):
            for x in (-1.7976931348623157e308, -1.0, -5e-324, -0.0, 0.0):
                with self.subTest(op=op, x=x):
                    with self.assertRaises(FloatFault) as caught:
                        FLOAT_PRIMS["float." + op](None, x)
                    self.assertEqual(caught.exception.op, "float." + op)
            self.assertEqual(result(op, 1.0), "0000000000000000")
        for x in (710.0, 1.7976931348623157e308):
            with self.assertRaises(FloatFault) as caught:
                FLOAT_PRIMS["float.exp"](None, x)
            self.assertEqual(caught.exception.op, "float.exp")
        self.assertEqual(result("exp", -1.7976931348623157e308), "0000000000000000")
        self.assertEqual(result("exp", -0.0), hexbits(1.0))
        self.assertGreater(FLOAT_PRIMS["float.exp"](None, -740.0), 0.0)

    def test_inverse_trig_exact_facts_and_domains(self):
        pi = FLOAT_PRIMS["float.pi"](None)
        for zero in (0.0, -0.0):
            for op in ("asin", "atan"):
                self.assertEqual(result(op, zero), hexbits(0.0))
            for x in (0.0, -0.0, 1.0):
                self.assertEqual(result("atan2", zero, x), hexbits(0.0))
            self.assertEqual(result("atan2", zero, -1.0), hexbits(pi))
        for op, args, expected in [
            ("asin", (1.0,), pi / 2), ("asin", (-1.0,), -pi / 2),
            ("acos", (1.0,), 0.0), ("acos", (-1.0,), pi),
            ("atan2", (1.0, -1.0), 3 * pi / 4),
            ("atan2", (-1.0, -1.0), -3 * pi / 4),
            ("atan2", (1.0, 1.0), pi / 4),
            ("atan2", (-1.0, 1.0), -pi / 4),
            ("atan2", (1.0, 0.0), pi / 2),
            ("atan2", (-1.0, 0.0), -pi / 2)]:
            self.assertEqual(result(op, *args), hexbits(expected))
        self.assertEqual(4.0 * FLOAT_PRIMS["float.atan"](None, 1.0), pi)
        for op in ("asin", "acos", "atan", "atan2"):
            invalid = [math.inf, -math.inf, math.nan]
            if op in ("asin", "acos"):
                invalid += [math.nextafter(1.0, math.inf), 2.0,
                            math.nextafter(-1.0, -math.inf), -2.0]
            for x in invalid:
                cases = [(x,)] if op != "atan2" else [(x, 1.0), (1.0, x)]
                for args in cases:
                    with self.subTest(op=op, args=args):
                        with self.assertRaises(FloatFault) as caught:
                            FLOAT_PRIMS["float." + op](None, *args)
                        self.assertEqual(caught.exception.op, "float." + op)

    def test_powers_of_two_exact(self):
        for exponent in range(-1074, 1024):
            self.assertEqual(FLOAT_PRIMS["float.log2"](None, math.ldexp(1.0, exponent)), float(exponent))

    def test_pow_cbrt_hypot_domains(self):
        for x in [0.0, -0.0, -1.7976931348623157e308, -2.0, 5e-324, 1e300]:
            self.assertEqual(result("pow", x, 0.0), hexbits(1.0))
        for y in [-1.7976931348623157e308, -3.0, 0.0, 5e-324, 1e300]:
            self.assertEqual(result("pow", 1.0, y), hexbits(1.0))
        for op, args in [("pow", (0.0, -1.0)), ("pow", (-0.0, -3.0)),
                         ("pow", (-8.0, 0.5)), ("pow", (-2.0, 1.5)),
                         ("pow", (2.0, 1024.0)), ("pow", (-2.0, 1025.0)),
                         ("hypot", (1.7976931348623157e308,) * 2)]:
            with self.subTest(op=op, args=args):
                with self.assertRaises(FloatFault) as caught:
                    FLOAT_PRIMS["float." + op](None, *args)
                self.assertEqual(caught.exception.op, "float." + op)
        for args, expected in [((-2.0, 3.0), -8.0), ((-2.0, 4.0), 16.0),
                               ((-2.0, -3.0), -0.125), ((2.0, -1074.0), 5e-324),
                               ((2.0, -1075.0), 0.0), ((-2.0, -1077.0), 0.0),
                               ((-0.0, 3.0), 0.0)]:
            self.assertEqual(result("pow", *args), hexbits(expected))
        self.assertEqual(result("cbrt", -0.0), hexbits(0.0))
        self.assertEqual(result("hypot", -0.0, -0.0), hexbits(0.0))
        self.assertEqual(result("hypot", 3.0, 4.0), hexbits(5.0))
        self.assertTrue(math.isfinite(FLOAT_PRIMS["float.hypot"](None, 1e300, 1e300)))

    def test_exact_cubes(self):
        for n in range(-100, 101):
            self.assertEqual(result("cbrt", float(n**3)), hexbits(float(n)))
        for exponent in range(-358, 342):
            root = math.ldexp(1.0, exponent)
            cube = math.ldexp(1.0, 3 * exponent)
            self.assertEqual(result("cbrt", cube), hexbits(root))
            self.assertEqual(result("cbrt", -cube), hexbits(-root))

    def test_exact_powers_of_ten_behavior(self):
        # 10**0 through 10**22 are exactly representable binary64 integers.
        for exponent in range(23):
            value = FLOAT_PRIMS["float.log10"](None, float(10**exponent))
            self.assertEqual(value, float(exponent), exponent)


HARNESS = r'''package main
import (
    "bufio"
    "fmt"
    "math"
    "os"
    "strconv"
    "strings"
)
func main() {
    in := bufio.NewScanner(os.Stdin)
    for in.Scan() {
        f := strings.Fields(in.Text())
        x := 0.0
        y := 0.0
        if len(f) > 1 {
            b, _ := strconv.ParseUint(f[1], 16, 64)
            x = math.Float64frombits(b)
        }
        if len(f) > 2 {
            b, _ := strconv.ParseUint(f[2], 16, 64)
            y = math.Float64frombits(b)
        }
        kind, v, _, ft := outcome(func() Value {
            switch f[0] {
            case "pi": return prim_float_pi()
            case "e": return prim_float_e()
            case "exp": return prim_float_exp(x)
            case "log1p": return prim_float_log1p(x)
            case "expm1": return prim_float_expm1(x)
            case "sinh": return prim_float_sinh(x)
            case "cosh": return prim_float_cosh(x)
            case "tanh": return prim_float_tanh(x)
            case "ln": return prim_float_ln(x)
            case "log2": return prim_float_log2(x)
            case "log10": return prim_float_log10(x)
            case "pow": return prim_float_pow(x, y)
            case "cbrt": return prim_float_cbrt(x)
            case "hypot": return prim_float_hypot(x, y)
            case "sin": return prim_float_sin(x)
            case "cos": return prim_float_cos(x)
            case "tan": return prim_float_tan(x)
            case "asin": return prim_float_asin(x)
            case "acos": return prim_float_acos(x)
            case "atan": return prim_float_atan(x)
            case "atan2": return prim_float_atan2(x, y)
            }
            panic("unknown op")
        })
        if kind == "fault" { fmt.Println(ft.D.Code) } else {
            fmt.Printf("%016x\n", math.Float64bits(v.(float64)))
        }
    }
}
'''


class FloatMathGoParity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if find_go() is None:
            import sys
            sys.stderr.write("\nSKIP: Go toolchain not found (PATH or LM_GO); Float math parity NOT run\n")
            raise unittest.SkipTest("go not found: Float math parity not run")
        cls.tmp = tempfile.mkdtemp(prefix="lm-float-math-")
        cls.addClassCleanup(shutil.rmtree, cls.tmp, ignore_errors=True)
        directory = Path(cls.tmp)
        for source in gobackend.RUNTIME.glob("*.go"):
            shutil.copyfile(source, directory / ("lm_" + source.name))
        (directory / "main.go").write_text(HARNESS)
        (directory / "go.mod").write_text(GO_MOD)
        cls.exe = directory / "harness"
        go_build(find_go(), directory, cls.exe)

    def test_vectors_and_random_bits(self):
        lines, expected = ["pi", "e"], [result("pi"), result("e")]
        rng = random.Random(5702)
        for op, rows in VECTORS.items():
            cases = [vector_args(row) for row in rows]
            xs = []
            xs.extend([0.0, -0.0, -1.0, -5e-324])
            if op in ("sin", "cos", "tan", "asin", "acos", "atan", "atan2", "log1p", "expm1",
                      "sinh", "cosh", "tanh"):
                xs.extend([math.inf, -math.inf, math.nan])
            if op == "log2":
                xs.extend(math.ldexp(1.0, exponent) for exponent in range(-1074, 1024))
            for _ in range(1500):
                bits = rng.randrange(0x7ff0000000000000)
                x = struct.unpack(">d", struct.pack(">Q", bits))[0]
                xs.append(-x if rng.randrange(2) else x)
            if op in ("exp", "expm1"):
                xs.extend(rng.uniform(-750.0, 710.0) for _ in range(1500))
            if op in ("sinh", "cosh", "tanh"):
                xs.extend(rng.uniform(-711.0, 711.0) for _ in range(1500))
            if op == "log1p":
                xs.extend(rng.uniform(-1.0, 1.0) for _ in range(1500))
            if op in ("asin", "acos"):
                xs.extend(rng.uniform(-1.0, 1.0) for _ in range(1500))
            if op in ("pow", "hypot", "atan2"):
                cases.extend(zip(xs, reversed(xs)))
                if op == "atan2":
                    cases.extend((y, x) for y in (0.0, -0.0, 1.0, -1.0)
                                 for x in (0.0, -0.0, 1.0, -1.0))
                if op == "pow":
                    cases.extend((rng.uniform(-10, 10), float(rng.randint(-100, 100)))
                                 for _ in range(500))
            else:
                cases.extend((x,) for x in xs)
            for args in cases:
                lines.append(op + " " + " ".join(hexbits(x) for x in args))
                expected.append(result(op, *args))
        proc = subprocess.run([str(self.exe)], input="\n".join(lines) + "\n",
                              capture_output=True, text=True, check=True)
        got = proc.stdout.splitlines()
        self.assertEqual(len(got), len(expected))
        differences = [f"{line}: Python {want}, Go {actual}" for line, want, actual
                       in zip(lines, expected, got) if actual != want]
        self.assertEqual(differences[:10], [])
