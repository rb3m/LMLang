"""Independent Decimal hyperbolic references and deterministic hard inputs."""
import decimal
import math
import random
import struct


def inputs(seed):
    rng = random.Random(seed + 6)
    hard = [0.0, 5e-324, 1e-323, 1e-300, 2.0**-1022,
            math.nextafter(2.0**-1022, 0.0), 30.0, 1e300,
            1.7976931348623157e308]
    thresholds = [2.0**-55, 2.0**-28, 1.0, 22.0,
                  709.782712893384, 710.4758600739439]
    # Actual high-word comparisons, including the ln(2)/2 cosh branch.
    for bits in [0x3fd62e4300000000, 0x40862e4200000000,
                 0x408633ce00000000]:
        thresholds.append(struct.unpack(">d", struct.pack(">Q", bits))[0])
    for x in thresholds:
        hard.extend([math.nextafter(x, -math.inf), x, math.nextafter(x, math.inf)])
    cases = {}
    for op in ("sinh", "cosh", "tanh"):
        values = [sign * x for x in hard for sign in (1, -1)]
        for n in range(200):
            if n % 2:
                bits = rng.randrange(1, 0x7ff0000000000000)
                x = struct.unpack(">d", struct.pack(">Q", bits))[0]
            else:
                x = rng.uniform(0.0, 711.0 if op != "tanh" else 30.0)
            values.append(-x if rng.randrange(2) else x)
        cases[op] = values
    return cases


def reference(op, x, precision):
    # These remote cutoffs avoid Decimal exponent limits, not edge decisions.
    if op != "tanh" and abs(x) > 711:
        return "E-FLOAT"
    if op == "tanh" and abs(x) > 100:
        return math.copysign(1.0, x).hex()
    with decimal.localcontext() as ctx:
        value = decimal.Decimal.from_float(x)
        # sinh/tanh cancellation at subnormal inputs needs >324 guard digits.
        ctx.prec = precision + (max(0, -value.adjusted()) + 20 if value else 0)
        positive, negative = value.exp(), (-value).exp()
        if op == "sinh":
            result = (positive - negative) / 2
        elif op == "cosh":
            result = (positive + negative) / 2
        else:
            result = (positive - negative) / (positive + negative)
        rounded = float(result)
        if rounded == 0:
            rounded = 0.0
        return rounded.hex() if math.isfinite(rounded) else "E-FLOAT"
