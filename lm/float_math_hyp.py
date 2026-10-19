"""LM float math algorithms v1: FreeBSD msun hyperbolic functions.

Ports of e_sinh.c, e_cosh.c, s_tanh.c and k_exp.c (__ldexp_exp):
https://github.com/freebsd/freebsd-src/tree/main/lib/msun/src
e_cosh.c also preserved at https://raw.githubusercontent.com/JuliaMath/openlibm/master/src/e_cosh.c
Use the pinned v1 exp/expm1, preserving word thresholds and evaluation order.
Floating exception flags are unobservable; float_prims checks finite results.
"""
# Copyright (C) 1993 by Sun Microsystems, Inc. All rights reserved.
# Developed at SunSoft (sinh/cosh) and SunPro (tanh), Sun Microsystems,
# Inc. businesses. Permission to use, copy, modify, and distribute this
# software is freely granted, provided that this notice is preserved.
#
# k_exp.c: Copyright (c) 2011 David Schultz <das@FreeBSD.ORG>
# All rights reserved.
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions
# are met:
# 1. Redistributions of source code must retain the above copyright
#    notice, this list of conditions and the following disclaimer.
# 2. Redistributions in binary form must reproduce the above copyright
#    notice, this list of conditions and the following disclaimer in the
#    documentation and/or other materials provided with the distribution.
# THIS SOFTWARE IS PROVIDED BY THE AUTHOR AND CONTRIBUTORS ``AS IS'' AND
# ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
# ARE DISCLAIMED. IN NO EVENT SHALL THE AUTHOR OR CONTRIBUTORS BE LIABLE
# FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
# DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS
# OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION)
# HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT
# LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY
# OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF
# SUCH DAMAGE.

import math

from .float_math import exp, from_bits
from .float_math_m1 import _bits, expm1


def _ldexp_exp(x, exponent):
    """msun scaled exp, for large positive x and exponent 0 or -1."""
    y = exp(x - 1246.97177782734161156)
    bits = _bits(y)
    exponent += (bits >> 52) - (1023 + 1023) + 1799
    y = from_bits((bits & 0xFFFFFFFFFFFFF) | (2046 << 52))
    scale = from_bits((1023 + exponent) << 52)
    return y * scale


def sinh(x):
    ax = abs(x)
    ix = _bits(ax) >> 32
    if ix >= 0x7FF00000:
        return x + x
    h = -0.5 if x < 0.0 else 0.5
    if ix < 0x40360000:
        if ix < 0x3E300000:
            return x
        t = expm1(ax)
        if ix < 0x3FF00000:
            return h * (2.0 * t - t * t / (t + 1.0))
        return h * (t + t / (t + 1.0))
    if ix < 0x40862E42:
        return h * exp(ax)
    if ix <= 0x408633CE:
        return (h * 2.0) * _ldexp_exp(ax, -1)
    return math.copysign(float("inf"), x)


def cosh(x):
    ax = abs(x)
    ix = _bits(ax) >> 32
    if ix >= 0x7FF00000:
        return x * x
    if ix < 0x3FD62E43:
        t = expm1(ax)
        w = 1.0 + t
        if ix < 0x3C800000:
            return w
        return 1.0 + (t * t) / (w + w)
    if ix < 0x40360000:
        t = exp(ax)
        return 0.5 * t + 0.5 / t
    if ix < 0x40862E42:
        return 0.5 * exp(ax)
    if ix <= 0x408633CE:
        return _ldexp_exp(ax, -1)
    return float("inf")


def tanh(x):
    ax = abs(x)
    ix = _bits(ax) >> 32
    if ix >= 0x7FF00000:
        # LM admits only finite Float inputs, including for saturated tanh.
        return float("nan")
    if ix < 0x40360000:
        if ix < 0x3E300000:
            return x
        if ix >= 0x3FF00000:
            t = expm1(2.0 * ax)
            z = 1.0 - 2.0 / (t + 2.0)
        else:
            t = expm1(-2.0 * ax)
            z = -t / (t + 2.0)
    else:
        z = 1.0
    return -z if x < 0.0 else z
