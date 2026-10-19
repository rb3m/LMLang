"""LM float math algorithms v1: FreeBSD msun e_pow.c (ADR-057).

Source: https://github.com/freebsd/freebsd-src/blob/main/lib/msun/src/e_pow.c
The logarithm/product/exponential splits retain the upstream rounding order.
Inputs are finite LM values; the prim wrapper checks non-finite outputs.
"""
# Copyright (C) 2004 by Sun Microsystems, Inc. All rights reserved.
# Permission to use, copy, modify, and distribute this software is freely
# granted, provided that this notice is preserved.

import math
import struct


def _bits(x):
    return struct.unpack(">Q", struct.pack(">d", x))[0]


def _from_bits(x):
    return struct.unpack(">d", struct.pack(">Q", x))[0]


def _high(x):
    return _bits(x) >> 32


def _low_zero(x):
    return _from_bits(_bits(x) & 0xffffffff00000000)


def pow(x, y):
    """msun pow for finite operands, with fault sentinels and normalized zero."""
    if y == 0.0 or x == 1.0:
        return 1.0
    if x == 0.0:
        return float("inf") if y < 0.0 else 0.0
    sign = 1.0
    if x < 0.0:
        if y != math.trunc(y):
            return float("nan")
        if abs(y) < 9007199254740992.0 and int(y) % 2:
            sign = -1.0
    if y == 1.0:
        return x
    if y == -1.0:
        return 1.0 / x
    if y == 2.0:
        return x * x
    if y == 0.5 and x > 0.0:
        return math.sqrt(x)
    ax = abs(x)
    if ax == 1.0:
        return sign
    ix = _high(ax)
    iy = _high(abs(y))
    if iy > 0x41e00000:
        if iy > 0x43f00000:
            if (ax < 1.0) == (y < 0.0):
                return sign * float("inf")
            return 0.0
        if ix < 0x3fefffff:
            return sign * float("inf") if y < 0.0 else 0.0
        if ix > 0x3ff00000:
            return sign * float("inf") if y > 0.0 else 0.0
        t = ax - 1.0
        w = (t * t) * (0.5 - t * (3.3333333333333331e-01 - t * 0.25))
        u = 1.44269502162933349609e+00 * t
        v = t * 1.92596299112661746887e-08 - w * 1.44269504088896338700e+00
        t1 = _low_zero(u + v)
        t2 = v - (t1 - u)
    else:
        n = 0
        if ix < 0x00100000:
            ax = ax * 9007199254740992.0
            n = n - 53
            ix = _high(ax)
        n = n + (ix >> 20) - 0x3ff
        j = ix & 0x000fffff
        ix = j | 0x3ff00000
        k = 0
        if j > 0x3988e:
            if j < 0xbb67a:
                k = 1
            else:
                n = n + 1
                ix = ix - 0x00100000
        ax = _from_bits((ix << 32) | (_bits(ax) & 0xffffffff))
        bp = 1.0 if k == 0 else 1.5
        dp_h = 0.0 if k == 0 else 5.84962487220764160156e-01
        dp_l = 0.0 if k == 0 else 1.35003920212974897128e-08
        u = ax - bp
        v = 1.0 / (ax + bp)
        ss = u * v
        s_h = _low_zero(ss)
        t_h = _from_bits((((ix >> 1) | 0x20000000) + 0x00080000 + (k << 18)) << 32)
        t_l = ax - (t_h - bp)
        s_l = v * ((u - s_h * t_h) - s_h * t_l)
        s2 = ss * ss
        r = s2 * s2 * (5.99999999999994648725e-01 + s2 * (4.28571428578550184252e-01 + s2 * (3.33333329818377432918e-01 + s2 * (2.72728123808534006489e-01 + s2 * (2.30660745775561754067e-01 + s2 * 2.06975017800338417784e-01)))))
        r = r + s_l * (s_h + ss)
        s2 = s_h * s_h
        t_h = _low_zero(3.0 + s2 + r)
        t_l = r - ((t_h - 3.0) - s2)
        u = s_h * t_h
        v = s_l * t_h + t_l * ss
        p_h = _low_zero(u + v)
        p_l = v - (p_h - u)
        z_h = 9.61796700954437255859e-01 * p_h
        z_l = -7.02846165095275826516e-09 * p_h + p_l * 9.61796693925975554329e-01 + dp_l
        t = float(n)
        t1 = _low_zero(((z_h + z_l) + dp_h) + t)
        t2 = z_l - (((t1 - t) - dp_h) - z_h)
    y1 = _low_zero(y)
    p_l = (y - y1) * t1 + y * t2
    p_h = y1 * t1
    z = p_l + p_h
    if z >= 1024.0:
        if z > 1024.0 or p_l + 8.0085662595372944372e-17 > z - p_h:
            return sign * float("inf")
    if z <= -1075.0:
        if z < -1075.0 or p_l <= z - p_h:
            return 0.0
    j = _high(z)
    i = j & 0x7fffffff
    k = (i >> 20) - 0x3ff
    n = 0
    if i > 0x3fe00000:
        n = j + (0x00100000 >> (k + 1))
        k = ((n & 0x7fffffff) >> 20) - 0x3ff
        t = _from_bits((n & ~(0x000fffff >> k)) << 32)
        n = ((n & 0x000fffff) | 0x00100000) >> (20 - k)
        if z < 0.0:
            n = -n
        p_h = p_h - t
    t = _low_zero(p_l + p_h)
    u = t * 6.93147182464599609375e-01
    v = (p_l - (t - p_h)) * 6.93147180559945286227e-01 + t * -1.90465429995776804525e-09
    z = u + v
    w = v - (z - u)
    t = z * z
    t1 = z - t * (1.66666666666666019037e-01 + t * (-2.77777777770155933842e-03 + t * (6.61375632143793436117e-05 + t * (-1.65339022054652515390e-06 + t * 4.13813679705723846039e-08))))
    r = (z * t1) / (t1 - 2.0) - (w + z * w)
    z = 1.0 - (r - z)
    try:
        return sign * math.ldexp(z, n)
    except OverflowError:
        return sign * float("inf")
