"""LM float math algorithms v1: FreeBSD msun s_log1p.c/s_expm1.c.

Sources: https://web.mit.edu/freebsd/head/lib/msun/src/s_log1p.c
(FreeBSD revision 251292, 2013-06-03)
https://raw.githubusercontent.com/freebsd/freebsd-src/main/lib/msun/src/s_expm1.c
Preserve msun's word thresholds, reduction and evaluation order. Floating
exception flags are not observable in LM; domain checks live in float_prims.
"""
# Copyright (C) 1993 by Sun Microsystems, Inc. All rights reserved.
# Developed at SunPro, a Sun Microsystems, Inc. business.
# Permission to use, copy, modify, and distribute this software is freely
# granted, provided that this notice is preserved.

import math
import struct

from .float_math import LN2_HI, LN2_LO, INV_LN2, from_bits


def _bits(x):
    return struct.unpack(">Q", struct.pack(">d", x))[0]


def log1p(x):
    if x <= -1.0:
        raise ValueError("log1p domain")
    if not math.isfinite(x):
        return x
    hx = _bits(x) >> 32
    ax = hx & 0x7FFFFFFF
    if hx & 0x80000000:
        hx -= 0x100000000
    k, c = 1, 0.0
    if hx < 0x3FDA827A:
        if ax < 0x3E200000:
            if ax < 0x3C900000:
                return x
            return x - x * x * 0.5
        if hx > 0 or hx <= 0xBFD2BEC4 - 0x100000000:
            k, f, hu = 0, x, 1
    if k != 0:
        if hx < 0x43400000:
            u = 1.0 + x
            hu = _bits(u) >> 32
            k = (hu >> 20) - 1023
            c = (1.0 - (u - x)) if k > 0 else (x - (u - 1.0))
            c /= u
        else:
            u = x
            hu = _bits(u) >> 32
            k = (hu >> 20) - 1023
        hu &= 0xFFFFF
        low = _bits(u) & 0xFFFFFFFF
        if hu < 0x6A09E:
            u = from_bits(((hu | 0x3FF00000) << 32) | low)
        else:
            k += 1
            u = from_bits(((hu | 0x3FE00000) << 32) | low)
            hu = (0x100000 - hu) >> 2
        f = u - 1.0
    hfsq = 0.5 * f * f
    if hu == 0:
        if f == 0.0:
            if k == 0:
                return 0.0
            c += k * LN2_LO
            return k * LN2_HI + c
        r = hfsq * (1.0 - 0.66666666666666666 * f)
        if k == 0:
            return f - r
        return k * LN2_HI - ((r - (k * LN2_LO + c)) - f)
    s = f / (2.0 + f)
    z = s * s
    p = 1.531383769920937332e-01 + z * 1.479819860511658591e-01
    p = 1.818357216161805012e-01 + z * p
    p = 2.222219843214978396e-01 + z * p
    p = 2.857142874366239149e-01 + z * p
    p = 3.999999999940941908e-01 + z * p
    r = z * (6.666666666666735130e-01 + z * p)
    if k == 0:
        return f - (hfsq - s * (hfsq + r))
    return k * LN2_HI - ((hfsq - (s * (hfsq + r) + (k * LN2_LO + c))) - f)


def expm1(x):
    if not math.isfinite(x):
        return float("nan")
    hx = (_bits(x) >> 32) & 0x7FFFFFFF
    if hx >= 0x4043687A:
        if x > 7.09782712893383973096e+02:
            return float("inf")
        if x < 0.0:
            return -1.0
    k, c = 0, 0.0
    if hx > 0x3FD62E42:
        if hx < 0x3FF0A2B2:
            if x > 0.0:
                hi, lo, k = x - LN2_HI, LN2_LO, 1
            else:
                hi, lo, k = x + LN2_HI, -LN2_LO, -1
        else:
            k = int(INV_LN2 * x + (0.5 if x > 0.0 else -0.5))
            t = float(k)
            hi = x - t * LN2_HI
            lo = t * LN2_LO
        x = hi - lo
        c = (hi - x) - lo
    elif hx < 0x3C900000:
        return x
    hfx = 0.5 * x
    hxs = x * hfx
    p = 4.00821782732936239552e-06 + hxs * -2.01099218183624371326e-07
    p = -7.93650757867487942473e-05 + hxs * p
    p = 1.58730158725481460165e-03 + hxs * p
    p = -3.33333333333331316428e-02 + hxs * p
    r1 = 1.0 + hxs * p
    t = 3.0 - r1 * hfx
    e = hxs * ((r1 - t) / (6.0 - x * t))
    if k == 0:
        return x - (x * e - hxs)
    e = (x * (e - c) - c) - hxs
    if k == -1:
        return 0.5 * (x - e) - 0.5
    if k == 1:
        if x < -0.25:
            return -2.0 * (e - (x + 0.5))
        return 1.0 + 2.0 * (x - e)
    if k <= -2 or k > 56:
        y = 1.0 - (e - x)
        if k == 1024:
            y = y * 2.0 * float.fromhex("0x1p1023")
        else:
            y *= from_bits((1023 + k) << 52)
        return y - 1.0
    if k < 20:
        t = from_bits((0x3FF00000 - (0x200000 >> k)) << 32)
        y = t - (e - x)
    else:
        t = from_bits((1023 - k) << 52)
        y = (x - (e + t)) + 1.0
    return y * from_bits((1023 + k) << 52)
