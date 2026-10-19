#!/usr/bin/env python3
"""Regenerate ADR-057 evidence using Decimal, independently of the runtime algorithms.

Inputs are exact binary64 values. Decimal's correctly rounded transcendental operations
are evaluated at 90 and 180 digits (extra cancellation digits for log1p/expm1);
their binary64 roundings must agree. This is strong
reference evidence, not a proof of correct rounding for every possible input.
"""
import decimal
import json
import math
import random
import struct
from fractions import Fraction
from functools import lru_cache
from pathlib import Path
import gen_float_hyp_vectors as hyperbolic

DEST = Path(__file__).resolve().parents[1] / "tests/unit/data/float_math_vectors.json"
SEED = 5701


def neighbors(x):
    return [math.nextafter(x, -math.inf), x, math.nextafter(x, math.inf)]


def inputs():
    rng = random.Random(SEED)
    logarithms = [5e-324, 1e-323, math.nextafter(2.0**-1022, 0.0),
                  2.0**-1022, 1.7976931348623157e308, 3.837687238376808e224]
    for x in [0.1, 0.5, 1.0, 2.0, 10.0, 100.0, 1000.0, 1e22, 1e100, 1e300]:
        logarithms.extend(neighbors(x))
    for exponent in [-1074, -1073, -1022, -1000, -100, -1, 0, 1, 10, 100, 1000, 1023]:
        logarithms.extend(x for x in neighbors(math.ldexp(1.0, exponent)) if x > 0)
    logarithms.extend(float(10**exponent) for exponent in range(23))
    for _ in range(200):
        bits = rng.randrange(1, 0x7ff0000000000000)
        logarithms.append(struct.unpack(">d", struct.pack(">Q", bits))[0])
    exponentials = [0.0, -0.0, 5e-324, -5e-324, 1e-300, -1e-300,
                    -1.7976931348623157e308, 1.7976931348623157e308]
    for x in [-1000.0, -800.0, -745.1332191019411, -744.4400719213812,
              -740.0, -708.3964185322641, -1.0, 1.0, 709.0,
              709.782712893384, 710.0, 1000.0]:
        exponentials.extend(neighbors(x))
    exponentials.extend(rng.uniform(-750.0, 710.0) for _ in range(200))
    powers_of_two = [math.ldexp(1.0, exponent) for exponent in range(-1074, 1024)]
    powers = [(0.0, 0.0), (-0.0, -1.0), (0.0, 2.0), (-2.0, 3.0),
              (-2.0, 4.0), (-8.0, 0.5), (-1.0, 1e300), (1.0, -1e300),
              (2.0, 1e300), (2.0, -1e300), (0.5, 1e300), (0.5, -1e300)]
    for x in [0.0, -0.0, -1e300, 5e-324, 1e300]:
        powers.append((x, 0.0))
    for x in [0.5, 2.0, 10.0]:
        for y in [-1075.0, -1074.0, -1022.0, 1024.0, 308.25471555991675]:
            powers.extend((x, z) for z in neighbors(y))
    for x in neighbors(1.0):
        powers.extend((x, y) for y in [-1e300, -1e18, -1e16, -1e-300,
                                      1e-300, 1e16, 1e18, 1e300])
    powers.extend((float(x), float(y)) for x in [-10, -3, -2, -1, 2, 3, 10]
                  for y in [-21, -3, -2, -1, 1, 2, 3, 21])
    cubes = [float(n**3) for n in range(-100, 101)]
    cubes.extend([5e-324, -5e-324, 1e-323, -1e-323, 2.0**-1022,
                  1.7976931348623157e308, -1.7976931348623157e308])
    hypots = [(3.0, 4.0), (-3.0, -4.0), (0.0, -0.0), (1e300, 1e300),
              (1e-300, 1e-300), (5e-324, 5e-324), (1e300, 5e-324)]
    for x in [5e-324, 2.0**-1022, 1.0, 1e300, 1.7976931348623157e308]:
        hypots.extend((x, y) for y in [0.0, x, x * 0.5, -x])
    for _ in range(200):
        x = math.ldexp(rng.uniform(0.5, 1.0), rng.randint(-1073, 1024))
        y = rng.uniform(-1100.0, 1100.0)
        powers.append((x, y))
        # Near-one bases and broad exponent magnitudes exercise cancellation.
        if _ < 50:
            powers.append((rng.choice(neighbors(1.0)), rng.uniform(-1e18, 1e18)))
        cubes.append(-x if rng.randrange(2) else x)
        z = math.ldexp(rng.uniform(0.5, 1.0), rng.randint(-1073, 1024))
        hypots.append((x, -z if rng.randrange(2) else z))
    return {"exp": exponentials, "ln": logarithms,
            "log2": logarithms + powers_of_two, "log10": logarithms,
            "pow": powers, "cbrt": cubes, "hypot": hypots,
            **trig_inputs(), **inverse_trig_inputs(), **m1_inputs(),
            **hyperbolic.inputs(SEED)}


def m1_inputs():
    rng = random.Random(SEED + 5)
    tiny = [0.0, 5e-324, 1e-323, 1e-300, 2.0**-1022,
            math.nextafter(2.0**-1022, 0.0)]
    shared = [s * x for x in tiny for s in (1, -1)]
    for x in [2.0**-54, 2.0**-29, math.log(2.0) / 2,
              1.5 * math.log(2.0), 1.0, 2.0]:
        shared.extend(s * y for y in neighbors(x) for s in (1, -1))
    logs = shared + [math.nextafter(-1.0, 0.0), -1.0 + 2.0**-52,
                     -1.0 + 2.0**-50, -1.7976931348623157e308]
    for x in [math.sqrt(2.0) - 1.0, math.sqrt(0.5) - 1.0,
              2.0**53, 1e100, 1e300, 1.7976931348623157e308]:
        logs.extend(y for y in neighbors(x) if math.isfinite(y))
    # msun compares high words; these boundaries differ from exact ln2/sqrt2.
    for bits in [0x3FDA827A00000000, 0xBFD2BEC400000000, 0xBFD2BEC500000000]:
        logs.extend(neighbors(struct.unpack(">d", struct.pack(">Q", bits))[0]))
    exps = shared + [-1.7976931348623157e308, 1.7976931348623157e308]
    for x in [-1000.0, -56.0 * math.log(2.0), -37.0, -2.0 * math.log(2.0),
              20.0 * math.log(2.0), 56.0 * math.log(2.0), 709.782712893384]:
        exps.extend(neighbors(x))
    for bits in [0x3FD62E4200000000, 0x3FD62E4300000000,
                 0x3FF0A2B200000000, 0x4043687A00000000]:
        x = struct.unpack(">d", struct.pack(">Q", bits))[0]
        exps.extend(s * y for y in neighbors(x) for s in (1, -1))
    for n in range(200):
        bits = rng.randrange(1, 0x7ff0000000000000)
        x = struct.unpack(">d", struct.pack(">Q", bits))[0]
        logs.append(rng.uniform(-1.0, 1.0) if n % 2 else x)
        if n % 2:
            bits = rng.randrange(1, 0x3ff0000000000000)
            x = struct.unpack(">d", struct.pack(">Q", bits))[0]
            exps.append(-x if rng.randrange(2) else x)
        else:
            exps.append(rng.uniform(-1000.0, 710.0))
    return {"log1p": logs, "expm1": exps}


def inverse_trig_inputs():
    rng = random.Random(SEED + 4)
    tiny = [0.0, 5e-324, 1e-323, 1e-300, 2.0**-1022,
            math.nextafter(2.0**-1022, 0.0)]
    bounded = tiny[:]
    for x in [2.0**-29, 0.4375, 0.5, 0.975, 1.0]:
        bounded.extend(neighbors(x))
    wide = bounded + [1e22, 1e300, 1.7976931348623157e308]
    for x in [0.6875, 1.1875, 2.4375, 2.0**66]:
        wide.extend(neighbors(x))
    cases = {}
    for op in ("asin", "acos", "atan"):
        values = [sign * x for x in (wide if op == "atan" else bounded)
                  for sign in (1, -1)]
        for _ in range(200):
            if op == "atan" or _ % 2:
                bits = rng.randrange(1, 0x7ff0000000000000 if op == "atan"
                                     else 0x3ff0000000000001)
                x = struct.unpack(">d", struct.pack(">Q", bits))[0]
            else:
                x = rng.random()
            values.append(-x if rng.randrange(2) else x)
        cases[op] = values
    axes = [0.0, 5e-324, 2.0**-1022, 1.0, 1e300, 1.7976931348623157e308]
    pairs = [(sy * y, sx * x) for y in axes for x in axes
             for sy in (1, -1) for sx in (1, -1)]
    for x in [2.0**-60, 2.0**60]:
        pairs.extend((sy * y, sx) for y in neighbors(x)
                     for sy in (1, -1) for sx in (1.0, -1.0))
    for _ in range(200):
        pair = []
        for _ in range(2):
            bits = rng.randrange(1, 0x7ff0000000000000)
            x = struct.unpack(">d", struct.pack(">Q", bits))[0]
            pair.append(-x if rng.randrange(2) else x)
        pairs.append(tuple(pair))
    cases["atan2"] = pairs
    return cases


def trig_inputs():
    rng = random.Random(SEED + 3)
    hard = [0.0, 5e-324, 1e-323, 1e-300, 2.0**-1022,
            math.nextafter(2.0**-1022, 0.0), 1e22, 1e300,
            1.7976931348623157e308, math.ldexp(6381956970095103.0, 797)]
    # Neighbors on either side of binary64 approximations to quadrant boundaries.
    for n in [1, 2, 3, 4, 5, 7, 8, 15, 16, 31, 32, 127, 128,
              1023, 1024, 2**19, 2**20, 2**32, 2**52]:
        hard.extend(neighbors(n * (math.pi / 4.0)))
    for x in [2.0**-27, 2.0**-28, 0.6744, 1.0, 1e22, 1e300,
              math.ldexp(6381956970095103.0, 797)]:
        hard.extend(neighbors(x))
    cases = {}
    for op in ("sin", "cos", "tan"):
        values = [sign * x for x in hard for sign in (1, -1)]
        for _ in range(200):
            bits = rng.randrange(1, 0x7ff0000000000000)
            x = struct.unpack(">d", struct.pack(">Q", bits))[0]
            values.append(-x if rng.randrange(2) else x)
        cases[op] = values
    return cases


@lru_cache(maxsize=2)
def decimal_pi(precision):
    """Gauss-Legendre pi, independently computed at each reference precision."""
    with decimal.localcontext() as ctx:
        ctx.prec = precision
        a, b = decimal.Decimal(1), decimal.Decimal(0.5).sqrt()
        t, p = decimal.Decimal(0.25), decimal.Decimal(1)
        # Quadratic convergence: 13 iterations exceed 1200 decimal digits.
        for _ in range(13):
            next_a = (a + b) / 2
            b = (a * b).sqrt()
            t -= p * (a - next_a) ** 2
            a, p = next_a, 2 * p
        return (a + b) ** 2 / (4 * t)


def trig_reference(op, value, precision):
    # Exact binary64 conversion can contain 1074 fractional digits. Keeping
    # >1100 digits also leaves ample guard digits after reducing max-float.
    with decimal.localcontext() as ctx:
        ctx.prec = precision + 1100
        half_pi = decimal_pi(ctx.prec) / 2
        quadrant = (value / half_pi).to_integral_value(rounding=decimal.ROUND_HALF_EVEN)
        reduced = value - quadrant * half_pi
    with decimal.localcontext() as ctx:
        ctx.prec = precision
        squared = -(reduced * reduced)
        sine, cosine = reduced, decimal.Decimal(1)
        sine_term, cosine_term = sine, cosine
        for n in range(1, precision + 20):
            sine_term *= squared / ((2 * n) * (2 * n + 1))
            cosine_term *= squared / ((2 * n - 1) * (2 * n))
            new_sine, new_cosine = sine + sine_term, cosine + cosine_term
            if (new_sine, new_cosine) == (sine, cosine):
                break
            sine, cosine = new_sine, new_cosine
        else:
            raise AssertionError("Decimal trig series did not converge")
        sine, cosine = [(sine, cosine), (cosine, -sine),
                        (-sine, -cosine), (-cosine, sine)][int(quadrant) % 4]
        return {"sin": sine, "cos": cosine, "tan": sine / cosine}[op]


def decimal_atan(value, pi):
    """Half-angle reduction followed by the independent alternating series."""
    negative, value = value < 0, abs(value)
    reciprocal = value > 1
    if reciprocal:
        value = 1 / value
    for _ in range(4):
        value /= 1 + (1 + value * value).sqrt()
    total, term, square = value, value, -(value * value)
    for n in range(1, decimal.getcontext().prec + 20):
        term *= square
        updated = total + term / (2 * n + 1)
        if updated == total:
            break
        total = updated
    else:
        raise AssertionError("Decimal atan series did not converge")
    total *= 16
    if reciprocal:
        total = pi / 2 - total
    return -total if negative else total


def inverse_trig_reference(op, value, args, precision):
    pi = decimal_pi(precision)
    if op == "atan":
        return decimal_atan(value, pi)
    if op == "atan2":
        x = decimal.Decimal.from_float(args[1])
        if value == 0:
            return pi if x < 0 else decimal.Decimal(0)
        if x == 0:
            return pi / 2 if value > 0 else -pi / 2
        angle = decimal_atan(value / x, pi)
        return angle if x > 0 else angle + (pi if value > 0 else -pi)
    if op == "acos":
        # Half-angle identity avoids subtraction of nearly equal angles at +1.
        if value == -1:
            return pi
        return 2 * decimal_atan(((1 - value) / (1 + value)).sqrt(), pi)
    if abs(value) == 1:
        return pi / 2 if value > 0 else -pi / 2
    return decimal_atan(value / ((1 - value) * (1 + value)).sqrt(), pi)


def reference(op, x, precision):
    if op in ("sinh", "cosh", "tanh"):
        return hyperbolic.reference(op, x, precision)
    # Avoid Decimal's own exponent limits for extreme finite binary64 arguments.
    if op in ("exp", "expm1") and x > 710:
        return "E-FLOAT"
    if op in ("exp", "expm1") and x < -800:
        return (-1.0 if op == "expm1" else 0.0).hex()
    with decimal.localcontext() as ctx:
        ctx.prec = precision
        args = x if isinstance(x, tuple) else (x,)
        value = decimal.Decimal.from_float(args[0])
        if op in ("log1p", "expm1") and value:
            # Addition/subtraction near 1 loses up to 324 decimal digits.
            ctx.prec += max(0, -value.adjusted()) + 20
        if op in ("asin", "acos") and abs(value) > 1:
            return "E-FLOAT"
        if op in ("asin", "acos", "atan", "atan2"):
            result = inverse_trig_reference(op, value, args, precision)
        elif op in ("sin", "cos", "tan"):
            result = trig_reference(op, value, precision)
        elif op == "log1p":
            if value <= -1:
                return "E-FLOAT"
            result = (1 + value).ln()
        elif op == "expm1":
            result = value.exp() - 1
        elif op == "exp":
            result = value.exp()
        elif op == "ln":
            result = value.ln()
        elif op == "log2":
            result = value.ln() / decimal.Decimal(2).ln()
        elif op == "log10":
            result = value.log10()
        elif op == "pow":
            exponent = decimal.Decimal.from_float(args[1])
            if exponent == 0 or value == 1:
                return 1.0.hex()
            if value == 0:
                return "E-FLOAT" if exponent < 0 else 0.0.hex()
            if value < 0 and exponent != exponent.to_integral_value():
                return "E-FLOAT"
            negative = value < 0 and int(exponent) % 2 != 0
            logarithm = abs(value).ln() * exponent
            if logarithm > 710:
                return "E-FLOAT"
            if logarithm < -800:
                return 0.0.hex()
            result = logarithm.exp()
            if negative:
                result = -result
        elif op == "cbrt":
            if value == 0:
                return 0.0.hex()
            magnitude = abs(value)
            estimate = decimal.Decimal(10) ** (magnitude.adjusted() // 3)
            for _ in range(precision + 20):
                updated = (2 * estimate + magnitude / (estimate * estimate)) / 3
                if abs(updated - estimate) <= abs(updated) * decimal.Decimal(10) ** (2 - precision):
                    estimate = updated
                    break
                estimate = updated
            else:
                raise AssertionError("Decimal cube root did not converge")
            result = -estimate if value < 0 else estimate
        elif op == "hypot":
            other = decimal.Decimal.from_float(args[1])
            result = (value * value + other * other).sqrt()
        else:
            raise AssertionError(op)
        rounded = float(result)
        # exp(y*ln(x)) can straddle an exact binary64 midpoint at any
        # Decimal precision (e.g. 2**-1075). Resolve these integer-power
        # ties with exact rational arithmetic, independently of the ports.
        if op == "pow" and args[1].is_integer() and abs(args[1]) <= 2048:
            exact = Fraction(args[0]) ** int(args[1])
            if math.isfinite(rounded):
                for direction in (-math.inf, math.inf):
                    adjacent = math.nextafter(rounded, direction)
                    if math.isfinite(adjacent) and exact == (Fraction(rounded) + Fraction(adjacent)) / 2:
                        rounded = float(exact)
                        break
        if rounded == 0.0:
            rounded = 0.0
        return rounded.hex() if math.isfinite(rounded) else "E-FLOAT"


def main():
    vectors = {}
    for op, values in inputs().items():
        vectors[op] = []
        for x in dict.fromkeys(values):
            expected = reference(op, x, 90)
            assert expected == reference(op, x, 180), (op, x)
            encoded = [a.hex() for a in x] if isinstance(x, tuple) else x.hex()
            vectors[op].append({"input": encoded, "expected": expected})
    DEST.parent.mkdir(parents=True, exist_ok=True)
    DEST.write_text(json.dumps({"algorithm": "LM float math algorithms v1",
                               "reference": "Decimal 90 and 180 digits; matching binary64 rounding; log1p/expm1 and hyperbolic functions add adaptive cancellation guard digits; trig reduction uses 1190/1280-digit Gauss-Legendre pi and Taylor series; inverse trig uses half-angle reduction and atan series",
                               "seed": SEED, "vectors": vectors}, indent=2) + "\n")
    print(f"Wrote {DEST}: " + ", ".join(f"{op}={len(rows)}" for op, rows in vectors.items()))


if __name__ == "__main__":
    main()
