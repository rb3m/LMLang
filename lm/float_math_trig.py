"""LM float math algorithms v1: FreeBSD msun s/k_sin, s/k_cos, s/k_tan.

Source: https://github.com/freebsd/freebsd-src/tree/main/lib/msun/src
Retrieved 2026-10-18; the port's result contract is pinned by the v1 tag.
All arithmetic follows the binary64 C expression order; no libm trig calls.
"""
# Copyright (C) 1993 by Sun Microsystems, Inc. All rights reserved.
# Developed at SunPro (s_sin/s_cos/s_tan) and SunSoft (k_sin/k_cos),
# Sun Microsystems, Inc. businesses.
# Copyright 2004 Sun Microsystems, Inc. All Rights Reserved. (k_tan)
# Permission to use, copy, modify, and distribute this software is freely
# granted, provided that this notice is preserved.

from .float_math import from_bits
from .float_math_reduce import bits, rem_pio2


def sin(x):
    ix = (bits(x) >> 32) & 0x7FFFFFFF
    if ix <= 0x3FE921FB:
        if ix < 0x3E500000:
            return x
        return kernel_sin(x, 0.0, False)
    if ix >= 0x7FF00000:
        return x - x
    n, y0, y1 = rem_pio2(x)
    n &= 3
    if n == 0:
        return kernel_sin(y0, y1, True)
    if n == 1:
        return kernel_cos(y0, y1)
    if n == 2:
        return -kernel_sin(y0, y1, True)
    return -kernel_cos(y0, y1)


def cos(x):
    ix = (bits(x) >> 32) & 0x7FFFFFFF
    if ix <= 0x3FE921FB:
        if ix < 0x3E46A09E:
            return 1.0
        return kernel_cos(x, 0.0)
    if ix >= 0x7FF00000:
        return x - x
    n, y0, y1 = rem_pio2(x)
    n &= 3
    if n == 0:
        return kernel_cos(y0, y1)
    if n == 1:
        return -kernel_sin(y0, y1, True)
    if n == 2:
        return -kernel_cos(y0, y1)
    return kernel_sin(y0, y1, True)


def tan(x):
    ix = (bits(x) >> 32) & 0x7FFFFFFF
    if ix <= 0x3FE921FB:
        if ix < 0x3E400000:
            return x
        return kernel_tan(x, 0.0, 1)
    if ix >= 0x7FF00000:
        return x - x
    n, y0, y1 = rem_pio2(x)
    return kernel_tan(y0, y1, 1 - ((n & 1) << 1))


def kernel_sin(x, y, tail):
    s1 = -1.66666666666666324348e-01
    s2 = 8.33333333332248946124e-03
    s3 = -1.98412698298579493134e-04
    s4 = 2.75573137070700676789e-06
    s5 = -2.50507602534068634195e-08
    s6 = 1.58969099521155010221e-10
    z = x * x
    w = z * z
    r = s2 + z * (s3 + z * s4) + z * w * (s5 + z * s6)
    v = z * x
    if not tail:
        return x + v * (s1 + z * r)
    return x - ((z * (0.5 * y - v * r) - y) - v * s1)


def kernel_cos(x, y):
    c1 = 4.16666666666666019037e-02
    c2 = -1.38888888888741095749e-03
    c3 = 2.48015872894767294178e-05
    c4 = -2.75573143513906633035e-07
    c5 = 2.08757232129817482790e-09
    c6 = -1.13596475577881948265e-11
    z = x * x
    w = z * z
    r = z * (c1 + z * (c2 + z * c3)) + w * w * (c4 + z * (c5 + z * c6))
    hz = 0.5 * z
    w = 1.0 - hz
    return w + (((1.0 - w) - hz) + (z * r - x * y))


T = (
    3.33333333333334091986e-01, 1.33333333333201242699e-01,
    5.39682539762260521377e-02, 2.18694882948595424599e-02,
    8.86323982359930005737e-03, 3.59207910759131235356e-03,
    1.45620945432529025516e-03, 5.88041240820264096874e-04,
    2.46463134818469906812e-04, 7.81794442939557092300e-05,
    7.14072491382608190305e-05, -1.85586374855275456654e-05,
    2.59073051863633712884e-05,
)


def kernel_tan(x, y, iy):
    hx = bits(x) >> 32
    ix = hx & 0x7FFFFFFF
    if ix >= 0x3FE59428:
        if hx >> 31:
            x, y = -x, -y
        z = 7.85398163397448278999e-01 - x
        w = 3.06161699786838301793e-17 - y
        x = z + w
        y = 0.0
    z = x * x
    w = z * z
    r = T[1] + w * (T[3] + w * (T[5] + w * (T[7] + w * (T[9] + w * T[11]))))
    v = z * (T[2] + w * (T[4] + w * (T[6] + w * (T[8] + w * (T[10] + w * T[12])))))
    s = z * x
    r = y + z * (s * (r + v) + y)
    r += T[0] * s
    w = x + r
    if ix >= 0x3FE59428:
        v = float(iy)
        return float(1 - ((hx >> 30) & 2)) * (v - 2.0 * (x - (w * w / (w + v) - r)))
    if iy == 1:
        return w
    z = from_bits(bits(w) & 0xFFFFFFFF00000000)
    v = r - (z - x)
    a = -1.0 / w
    t = from_bits(bits(a) & 0xFFFFFFFF00000000)
    s = 1.0 + t * z
    return t + a * (s + t * v)
