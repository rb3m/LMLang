"""LM float math algorithms v1: FreeBSD msun s_cbrt.c and e_hypot.c.

Sources: https://github.com/freebsd/freebsd-src/blob/main/lib/msun/src/s_cbrt.c
https://github.com/JuliaMath/openlibm/blob/master/src/e_hypot.c
(FreeBSD e_hypot.c revision 1.14). No platform transcendentals.
Domain and finite-result checks belong to float_prims.
"""
# Copyright (C) 1993 by Sun Microsystems, Inc. All rights reserved.
# Developed at SunPro (s_cbrt.c) and SunSoft (e_hypot.c), Sun Microsystems,
# Inc. businesses. Permission to use, copy, modify, and distribute this
# software is freely granted, provided that this notice is preserved.
# s_cbrt.c optimized by Bruce D. Evans.

import math
import struct

from .float_math import from_bits


def _bits(x):
    return struct.unpack(">Q", struct.pack(">d", x))[0]


def cbrt(x):
    """Bit seed, degree-four correction, then a rounded Halley step."""
    bits = _bits(x)
    sign = bits & (1 << 63)
    hx = (bits >> 32) & 0x7fffffff
    if hx >= 0x7ff00000 or x == 0.0:
        return x
    if hx < 0x00100000:
        high = (_bits(x * 2.0**54) >> 32) & 0x7fffffff
        t = from_bits(sign | ((high // 3 + 696219795) << 32))
    else:
        t = from_bits(sign | ((hx // 3 + 715094163) << 32))
    p0 = 1.87595182427177009643
    p1 = -1.88497979543377169875
    p2 = 1.621429720105354466140
    p3 = -0.758397934778766047437
    p4 = 0.145996192886612446982
    r = (t * t) * (t / x)
    t = t * ((p0 + r * (p1 + r * p2)) + ((r * r) * r) * (p3 + r * p4))
    t = from_bits((_bits(t) + 0x80000000) & 0xffffffffc0000000)
    s = t * t
    r = x / s
    w = t + t
    r = (r - t) / (w + r)
    return t + t * r


def hypot(x, y):
    """Scale before the compensated sum of squares and correctly rounded sqrt."""
    a, b = abs(x), abs(y)
    ha, hb = _bits(a) >> 32, _bits(b) >> 32
    if hb > ha:
        a, b, ha, hb = b, a, hb, ha
    if ha - hb > 0x3c00000:
        return a + b
    k = 0
    if ha > 0x5f300000:
        if ha >= 0x7ff00000:
            return a + b
        a *= 2.0**-600
        b *= 2.0**-600
        ha -= 0x25800000
        hb -= 0x25800000
        k = 600
    if hb < 0x20b00000:
        if hb <= 0x000fffff:
            if b == 0.0:
                return a
            a *= 2.0**1022
            b *= 2.0**1022
            k -= 1022
        else:
            a *= 2.0**600
            b *= 2.0**600
            ha += 0x25800000
            hb += 0x25800000
            k -= 600
    w = a - b
    if w > b:
        t1 = from_bits(ha << 32)
        t2 = a - t1
        w = math.sqrt(t1 * t1 - (b * (-b) - t2 * (a + t1)))
    else:
        a = a + a
        y1 = from_bits(hb << 32)
        y2 = b - y1
        t1 = from_bits((ha + 0x00100000) << 32)
        t2 = a - t1
        w = math.sqrt(t1 * y1 - (w * (-w) - (t1 * y2 + t2 * b)))
    return (2.0**k) * w if k else w
