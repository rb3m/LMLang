"""Python implementations of the Float prims: module `float` and `str.from-float`/`str.to-float` (ADR-039)."""
from __future__ import annotations

import math
import re

from . import float_math, float_math_atrig, float_math_hyp, float_math_m1, float_math_pow, float_math_roots, float_math_trig
from .printer import float_text
from .values import FloatFault, Overflow, Var, in_range

NONE = Var("", "None")
# str.to-float: optional sign, digits with an optional fraction (either side of `.` may be empty, not
# both), optional exponent. No whitespace, `_`, hex, `inf` or `nan`.
DECIMAL_RE = re.compile(r"[+-]?([0-9]+(\.[0-9]*)?|\.[0-9]+)([eE][+-]?[0-9]+)?")


def to_int(op, x, n):
    """The mathematical integer n (already rounded from x) as an Int, or the fault E-OVERFLOW."""
    if in_range(n):
        return n
    raise Overflow(op, (x,))


def round_half_away(x: float) -> int:
    t = math.trunc(x)
    if abs(x - t) >= 0.5:  # x - trunc(x) is exact
        return t + (1 if x > 0 else -1)
    return t


def from_int(it, n):
    return float(n) + 0.0  # nearest binary64, ties to even


def sqrt(it, x):
    if x < 0:
        raise FloatFault("float.sqrt", (x,))
    return math.sqrt(x)


def from_float(it, x):
    return float_text(x)


def fixed(it, x, digits):
    """Round the exact binary ratio, half to even, using unbounded integer arithmetic."""
    numerator, denominator = abs(x).as_integer_ratio()
    scaled, remainder = divmod(numerator * 10 ** digits, denominator)
    if remainder * 2 > denominator or (remainder * 2 == denominator and scaled % 2):
        scaled += 1
    text = str(scaled).zfill(digits + 1)
    if digits:
        text = text[:-digits] + "." + text[-digits:]
    return ("-" if x < 0 and scaled else "") + text


def math_prim(name, fn, positive=False):
    """Shared domain/result checks for versioned Float math algorithms."""
    def checked(it, *args):
        if positive and args[0] <= 0.0:
            raise FloatFault(name, args)
        try:
            result = fn(*args)
        except (OverflowError, ValueError, ZeroDivisionError):
            raise FloatFault(name, args) from None
        if not math.isfinite(result):
            raise FloatFault(name, args)
        return result + 0.0
    return checked


def to_float(it, s):
    if not DECIMAL_RE.fullmatch(s):
        return NONE
    v = float(s)
    return Var("", "Some", (v + 0.0,)) if math.isfinite(v) else NONE


FLOAT_PRIMS = {
    "float.fixed": fixed,
    "float.sinh": math_prim("float.sinh", float_math_hyp.sinh),
    "float.cosh": math_prim("float.cosh", float_math_hyp.cosh),
    "float.tanh": math_prim("float.tanh", float_math_hyp.tanh),

    "float.log1p": math_prim("float.log1p", float_math_m1.log1p),
    "float.expm1": math_prim("float.expm1", float_math_m1.expm1),
    "float.asin": math_prim("float.asin", float_math_atrig.asin),
    "float.acos": math_prim("float.acos", float_math_atrig.acos),
    "float.atan": math_prim("float.atan", float_math_atrig.atan),
    "float.atan2": math_prim("float.atan2", float_math_atrig.atan2),
    "float.sin": math_prim("float.sin", float_math_trig.sin),
    "float.cos": math_prim("float.cos", float_math_trig.cos),
    "float.tan": math_prim("float.tan", float_math_trig.tan),
    "float.pow": math_prim("float.pow", float_math_pow.pow),
    "float.cbrt": math_prim("float.cbrt", float_math_roots.cbrt),
    "float.hypot": math_prim("float.hypot", float_math_roots.hypot),
    "float.pi": lambda it: float_math.PI,
    "float.e": lambda it: float_math.E,
    "float.exp": math_prim("float.exp", float_math.exp),
    "float.ln": math_prim("float.ln", float_math.ln, positive=True),
    "float.log2": math_prim("float.log2", float_math.log2, positive=True),
    "float.log10": math_prim("float.log10", float_math.log10, positive=True),
    "float.from-int": from_int, "float.sqrt": sqrt,
    "float.floor": lambda it, x: to_int("float.floor", x, math.floor(x)),
    "float.ceil": lambda it, x: to_int("float.ceil", x, math.ceil(x)),
    "float.round": lambda it, x: to_int("float.round", x, round_half_away(x)),
    "float.trunc": lambda it, x: to_int("float.trunc", x, math.trunc(x)),
    "str.from-float": from_float, "str.to-float": to_float,
}
