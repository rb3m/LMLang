"""LM float math algorithms v1: FreeBSD msun inverse trigonometry.

Ports of e_asin.c, e_acos.c, s_atan.c, e_atan2.c; binary64 C order.
Source: https://github.com/freebsd/freebsd-src/tree/main/lib/msun/src
Only correctly rounded sqrt and exact bit operations use platform helpers.
"""
# Copyright (C) 1993 by Sun Microsystems, Inc. All rights reserved.
# Developed at SunSoft (asin/acos/atan2) and SunPro (atan),
# Sun Microsystems, Inc. businesses.
# Permission to use, copy, modify, and distribute this software is freely
# granted, provided that this notice is preserved.

import math

from .float_math import PI, from_bits
from .float_math_reduce import bits

PIO2_HI = 1.57079632679489655800e+00
PIO2_LO = 6.12323399573676603587e-17
PIO4_HI = 7.85398163397448278999e-01
PI_LO = 1.2246467991473531772e-16


def asin_ratio(z):
    p = z * (1.66666666666666657415e-01 + z * (
        -3.25565818622400915405e-01 + z * (2.01212532134862925881e-01
        + z * (-4.00555345006794114027e-02 + z * (
            7.91534994289814532176e-04 + z * 3.47933107596021167570e-05)))))
    q = 1.0 + z * (-2.40339491173441421878e+00 + z * (
        2.02094576023350569471e+00 + z * (-6.88283971605453293030e-01
        + z * 7.70381505559019352791e-02)))
    return p / q


def asin(x):
    ix = (bits(x) >> 32) & 0x7fffffff
    if abs(x) >= 1.0:
        if abs(x) == 1.0:
            return x * PIO2_HI + x * PIO2_LO
        raise ValueError("asin domain")
    if ix < 0x3fe00000:
        if ix < 0x3e400000:
            return x
        return x + x * asin_ratio(x * x)
    t = (1.0 - abs(x)) * 0.5
    r = asin_ratio(t)
    s = math.sqrt(t)
    if ix >= 0x3fef3333:
        t = PIO2_HI - (2.0 * (s + s * r) - PIO2_LO)
    else:
        w = from_bits(bits(s) & 0xffffffff00000000)
        c = (t - w * w) / (s + w)
        p = 2.0 * s * r - (PIO2_LO - 2.0 * c)
        q = PIO4_HI - 2.0 * w
        t = PIO4_HI - (p - q)
    return -t if x < 0.0 else t


def acos(x):
    ix = (bits(x) >> 32) & 0x7fffffff
    if abs(x) >= 1.0:
        if x == 1.0:
            return 0.0
        if x == -1.0:
            return PI + 2.0 * PIO2_LO
        raise ValueError("acos domain")
    if ix < 0x3fe00000:
        if ix <= 0x3c600000:
            return PIO2_HI + PIO2_LO
        r = asin_ratio(x * x)
        return PIO2_HI - (x - (PIO2_LO - x * r))
    if x < 0.0:
        z = (1.0 + x) * 0.5
        s = math.sqrt(z)
        w = asin_ratio(z) * s - PIO2_LO
        return PI - 2.0 * (s + w)
    z = (1.0 - x) * 0.5
    s = math.sqrt(z)
    df = from_bits(bits(s) & 0xffffffff00000000)
    c = (z - df * df) / (s + df)
    w = asin_ratio(z) * s + c
    return 2.0 * (df + w)


ATAN_HI = (4.63647609000806093515e-01, PIO4_HI,
           9.82793723247329054082e-01, PIO2_HI)
ATAN_LO = (2.26987774529616870924e-17, 3.06161699786838301793e-17,
           1.39033110312309984516e-17, PIO2_LO)
AT = (3.33333333333329318027e-01, -1.99999999998764832476e-01,
      1.42857142725034663711e-01, -1.11111104054623557880e-01,
      9.09088713343650656196e-02, -7.69187620504482999495e-02,
      6.66107313738753120669e-02, -5.83357013379057348645e-02,
      4.97687799461593236017e-02, -3.65315727442169155270e-02,
      1.62858201153657823623e-02)


def atan(x):
    if not math.isfinite(x):
        raise ValueError("atan requires finite input")
    ix = (bits(x) >> 32) & 0x7fffffff
    negative = x < 0.0
    if ix >= 0x44100000:
        if math.isnan(x):
            return x
        return -PIO2_HI - PIO2_LO if negative else PIO2_HI + PIO2_LO
    ident = -1
    if ix < 0x3fdc0000:
        if ix < 0x3e400000:
            return x
    else:
        x = abs(x)
        if ix < 0x3fe60000:
            ident, x = 0, (2.0 * x - 1.0) / (2.0 + x)
        elif ix < 0x3ff30000:
            ident, x = 1, (x - 1.0) / (x + 1.0)
        elif ix < 0x40038000:
            ident, x = 2, (x - 1.5) / (1.0 + 1.5 * x)
        else:
            ident, x = 3, -1.0 / x
    z = x * x
    w = z * z
    s1 = z * (AT[0] + w * (AT[2] + w * (AT[4] + w * (AT[6] + w * (AT[8] + w * AT[10])))))
    s2 = w * (AT[1] + w * (AT[3] + w * (AT[5] + w * (AT[7] + w * AT[9]))))
    if ident < 0:
        return x - x * (s1 + s2)
    z = ATAN_HI[ident] - ((x * (s1 + s2) - ATAN_LO[ident]) - x)
    return -z if negative else z


def atan2(y, x):
    """msun quadrant reduction for finite LM inputs; LM normalizes -0."""
    if not math.isfinite(x) or not math.isfinite(y):
        raise ValueError("atan2 requires finite inputs")
    x, y = (0.0 if x == 0.0 else x), (0.0 if y == 0.0 else y)
    if x == 1.0:
        return atan(y)
    if y == 0.0:
        return PI if x < 0.0 else 0.0
    if x == 0.0:
        return -PIO2_HI if y < 0.0 else PIO2_HI
    ix = (bits(x) >> 32) & 0x7fffffff
    iy = (bits(y) >> 32) & 0x7fffffff
    m = (2 if x < 0.0 else 0) + (1 if y < 0.0 else 0)
    k = (iy - ix) >> 20
    if k > 60:
        z = PIO2_HI + 0.5 * PI_LO
        m &= 1
    elif x < 0.0 and k < -60:
        z = 0.0
    else:
        z = atan(abs(y / x))
    if m == 0:
        return z
    if m == 1:
        return -z
    if m == 2:
        return PI - (z - PI_LO)
    return (z - PI_LO) - PI
