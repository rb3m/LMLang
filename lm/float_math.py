"""LM float math algorithms v1: pinned Go/msun reference (ADR-057).

exp/ln: Go 1.27.2 src/math/{exp,log}.go. log2/log10: FreeBSD msun
e_log2.c, e_log10.c and k_log.h, as imported in Android bionic a0ee078.
Source: https://android.googlesource.com/platform/bionic/+/a0ee078%5E%21/
Domain/finite-result checks belong to float_prims. No platform transcendentals.
"""
# Copyright 2009 The Go Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license.
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
# * Redistributions of source code must retain the above copyright notice,
#   this list of conditions and the following disclaimer.
# * Redistributions in binary form must reproduce the above copyright notice,
#   this list of conditions and the following disclaimer in the documentation
#   and/or other materials provided with the distribution.
# * Neither the name of Google Inc. nor the names of its contributors may be
#   used to endorse or promote products derived from this software without
#   specific prior written permission.
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
# ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE
# LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
# CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
# SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
# INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
# CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
# ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.
#
# Original FreeBSD msun e_exp.c and e_log.c notices:
# Copyright (C) 2004 by Sun Microsystems, Inc. All rights reserved.
# Copyright (C) 1993 by Sun Microsystems, Inc. All rights reserved.
# Developed at SunPro, a Sun Microsystems, Inc. business.
# e_log2.c/e_log10.c/k_log.h: Developed at SunSoft, a Sun Microsystems,
# Inc. business. Copyright (C) 1993 by Sun Microsystems, Inc.
# Permission to use, copy, modify, and distribute this software is freely
# granted, provided that this notice is preserved.

import math
import struct


def from_bits(bits):
    return struct.unpack(">d", struct.pack(">Q", bits))[0]


PI = from_bits(0x400921FB54442D18)
E = from_bits(0x4005BF0A8B145769)
LN2_HI = 6.93147180369123816490e-01
LN2_LO = 1.90821492927058770002e-10
INV_LN2 = float.fromhex("0x1.71547652b82fep+0")


def exp(x):
    if x > 7.09782712893383973096e+02:
        return float("inf")
    if x < -7.45133219101941108420e+02:
        return 0.0
    if -2.0**-28 < x < 2.0**-28:
        return 1.0 + x
    k = int(INV_LN2 * x + (0.5 if x > 0.0 else -0.5))
    hi = x - float(k) * LN2_HI
    lo = float(k) * LN2_LO
    return expmulti(hi, lo, k)


def expmulti(hi, lo, k):
    """e**(hi-lo) times 2**k; preserve expression evaluation order."""
    p1 = 1.66666666666666657415e-01
    p2 = -2.77777777770155933842e-03
    p3 = 6.61375632143793436117e-05
    p4 = -1.65339022054652515390e-06
    p5 = 4.13813679705723846039e-08
    r = hi - lo
    t = r * r
    c = r - t * (p1 + t * (p2 + t * (p3 + t * (p4 + t * p5))))
    y = 1.0 - ((lo - (r * c) / (2.0 - c)) - hi)
    try:
        return math.ldexp(y, k)
    except OverflowError:
        return float("inf")


def ln(x):
    l1 = 6.666666666666735130e-01
    l2 = 3.999999999940941908e-01
    l3 = 2.857142874366239149e-01
    l4 = 2.222219843214978396e-01
    l5 = 1.818357216161805012e-01
    l6 = 1.531383769920937332e-01
    l7 = 1.479819860511658591e-01
    f1, ki = math.frexp(x)
    if f1 < float.fromhex("0x1.6a09e667f3bcdp-1"):
        f1 *= 2.0
        ki -= 1
    f = f1 - 1.0
    k = float(ki)
    s = f / (2.0 + f)
    s2 = s * s
    s4 = s2 * s2
    t1 = s2 * (l1 + s4 * (l3 + s4 * (l5 + s4 * l7)))
    t2 = s4 * (l2 + s4 * (l4 + s4 * l6))
    r = t1 + t2
    hfsq = 0.5 * f * f
    return k * LN2_HI - ((hfsq - (s * (hfsq + r) + k * LN2_LO)) - f)


def log2(x):
    hi, lo, y = log_parts(x)
    inv_hi = 1.44269504072144627571e+00
    inv_lo = 1.67517131648865118353e-10
    val_hi = hi * inv_hi
    val_lo = (lo + hi) * inv_lo + lo * inv_hi
    w = y + val_hi
    val_lo += (y - w) + val_hi
    return val_lo + w


def log10(x):
    hi, lo, y = log_parts(x)
    inv_hi = 4.34294481878168880939e-01
    inv_lo = 2.50829467116452752298e-11
    log2_hi = 3.01029995663611771306e-01
    log2_lo = 3.69423907715893078616e-13
    val_hi = hi * inv_hi
    y2 = y * log2_hi
    val_lo = y * log2_lo + (lo + hi) * inv_lo + lo * inv_hi
    w = y2 + val_hi
    val_lo += (y2 - w) + val_hi
    return val_lo + w


def log_parts(x):
    """msun reduction and k_log1p, split log(1+f) into high/low parts.

    Frexp handles subnormals exactly. Retain msun's high-word reduction
    boundary (slightly below sqrt(2)), then clear hi's low 32 bits. The
    split and compensated additions avoid cancellation close to 1.
    """
    frac, k = math.frexp(x)
    frac *= 2.0
    k -= 1
    bits = struct.unpack(">Q", struct.pack(">d", frac))[0]
    if ((bits >> 32) & 0xFFFFF) >= 0x6A09C:
        frac *= 0.5
        k += 1
    f = frac - 1.0
    l1 = 6.666666666666735130e-01
    l2 = 3.999999999940941908e-01
    l3 = 2.857142874366239149e-01
    l4 = 2.222219843214978396e-01
    l5 = 1.818357216161805012e-01
    l6 = 1.531383769920937332e-01
    l7 = 1.479819860511658591e-01
    s = f / (2.0 + f)
    z = s * s
    w = z * z
    t1 = w * (l2 + w * (l4 + w * l6))
    t2 = z * (l1 + w * (l3 + w * (l5 + w * l7)))
    r = t2 + t1
    hfsq = 0.5 * f * f
    r = s * (hfsq + r)
    hi = f - hfsq
    hi = from_bits(struct.unpack(">Q", struct.pack(">d", hi))[0] & 0xFFFFFFFF00000000)
    lo = (f - hi) - hfsq + r
    return hi, lo, float(k)
