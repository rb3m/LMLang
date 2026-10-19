"""LM float math algorithms v1: FreeBSD msun e_rem_pio2/k_rem_pio2.

Source: https://github.com/freebsd/freebsd-src/tree/main/lib/msun/src
Retrieved 2026-10-18; the port's result contract is pinned by the v1 tag.
Binary64 specialization (prec=1); shared Payne-Hanek range reduction.
"""
# Copyright (C) 1993 by Sun Microsystems, Inc. All rights reserved.
# Developed at SunSoft, a Sun Microsystems, Inc. business.
# Permission to use, copy, modify, and distribute this software is freely
# granted, provided that this notice is preserved.
# e_rem_pio2 optimized by Bruce D. Evans.

import math
import struct

from .float_math import from_bits


def bits(x):
    return struct.unpack(">Q", struct.pack(">d", x))[0]


IPIO2 = (
    0xA2F983, 0x6E4E44, 0x1529FC, 0x2757D1, 0xF534DD, 0xC0DB62,
    0x95993C, 0x439041, 0xFE5163, 0xABDEBB, 0xC561B7, 0x246E3A,
    0x424DD2, 0xE00649, 0x2EEA09, 0xD1921C, 0xFE1DEB, 0x1CB129,
    0xA73EE8, 0x8235F5, 0x2EBB44, 0x84E99C, 0x7026B4, 0x5F7E41,
    0x3991D6, 0x398353, 0x39F49C, 0x845F8B, 0xBDF928, 0x3B1FF8,
    0x97FFDE, 0x05980F, 0xEF2F11, 0x8B5A0A, 0x6D1F6D, 0x367ECF,
    0x27CB09, 0xB74F46, 0x3F669E, 0x5FEA2D, 0x7527BA, 0xC7EBE5,
    0xF17B3D, 0x0739F7, 0x8A5292, 0xEA6BFB, 0x5FB11F, 0x8D5D08,
    0x560330, 0x46FC7B, 0x6BABF0, 0xCFBC20, 0x9AF436, 0x1DA9E3,
    0x91615E, 0xE61B08, 0x659985, 0x5F14A0, 0x68408D, 0xFFD880,
    0x4D7327, 0x310606, 0x1556CA, 0x73A8C9, 0x60E27B, 0xC08C6B,
)
PIO2 = (
    1.57079625129699707031e+00, 7.54978941586159635335e-08,
    5.39030252995776476554e-15, 3.28200341580791294123e-22,
    1.27065575308067607349e-29, 1.22933308981111328932e-36,
    2.73370053816464559624e-44, 2.16741683877804819444e-51,
)
TWO24 = 16777216.0
TWON24 = 5.9604644775390625e-08
PIO2_1 = 1.57079632673412561417e+00
PIO2_1T = 6.07710050650619224932e-11
PIO2_2 = 6.07710050630396597660e-11
PIO2_2T = 2.02226624879595063154e-21
PIO2_3 = 2.02226624871116645580e-21
PIO2_3T = 8.47842766036889956997e-32


def rem_pio2(x):
    """Return n, head, tail with x = n*pi/2 + head + tail (n mod 8)."""
    hx = bits(x) >> 32
    ix = hx & 0x7FFFFFFF
    n = 0
    if ix <= 0x400F6A7A:
        if (ix & 0xFFFFF) != 0x921FB:
            n = 1 if ix <= 0x4002D97C else 2
    elif ix <= 0x401C463B:
        if ix <= 0x4015FDBC:
            if ix != 0x4012D97C:
                n = 3
        elif ix != 0x401921FB:
            n = 4
    if n:
        if hx >> 31:
            z = x + float(n) * PIO2_1
            y0 = z + float(n) * PIO2_1T
            return -n, y0, (z - y0) + float(n) * PIO2_1T
        z = x - float(n) * PIO2_1
        y0 = z - float(n) * PIO2_1T
        return n, y0, (z - y0) - float(n) * PIO2_1T
    if ix < 0x413921FB:
        fn = float(round(x * 6.36619772367581382433e-01))
        n = int(fn)
        r = x - fn * PIO2_1
        w = fn * PIO2_1T
        j = ix >> 20
        y0 = r - w
        i = j - ((bits(y0) >> 52) & 0x7FF)
        if i > 16:
            t = r
            w = fn * PIO2_2
            r = t - w
            w = fn * PIO2_2T - ((t - r) - w)
            y0 = r - w
            i = j - ((bits(y0) >> 52) & 0x7FF)
            if i > 49:
                t = r
                w = fn * PIO2_3
                r = t - w
                w = fn * PIO2_3T - ((t - r) - w)
                y0 = r - w
        return n, y0, (r - y0) - w
    if ix >= 0x7FF00000:
        return 0, x - x, x - x
    e0 = (ix >> 20) - 1046
    z = from_bits(((ix - (e0 << 20)) << 32) | (bits(x) & 0xFFFFFFFF))
    tx = []
    for _ in range(2):
        tx.append(float(int(z)))
        z = (z - tx[-1]) * TWO24
    tx.append(z)
    while tx[-1] == 0.0:
        tx.pop()
    n, y0, y1 = kernel_rem_pio2(tx, e0)
    return (-n, -y0, -y1) if hx >> 31 else (n, y0, y1)


def kernel_rem_pio2(x, e0):
    """msun's 24-bit chunk convolution; bounded integer work, no big ints."""
    jk = 4
    jx = len(x) - 1
    jv = max(0, (e0 - 3) // 24)
    q0 = e0 - 24 * (jv + 1)
    f, fq, q = [0.0] * 20, [0.0] * 20, [0.0] * 20
    iq = [0] * 20
    for i in range(jx + jk + 1):
        j = jv - jx + i
        f[i] = 0.0 if j < 0 else float(IPIO2[j])
    for i in range(jk + 1):
        fw = 0.0
        for j in range(jx + 1):
            fw += x[j] * f[jx + i - j]
        q[i] = fw
    jz = jk
    while True:
        z = q[jz]
        for i, j in enumerate(range(jz, 0, -1)):
            fw = float(int(TWON24 * z))
            iq[i] = int(z - TWO24 * fw)
            z = q[j - 1] + fw
        z = math.ldexp(z, q0)
        z -= 8.0 * float(math.floor(z * 0.125))
        n = int(z)
        z -= float(n)
        ih = 0
        if q0 > 0:
            i = iq[jz - 1] >> (24 - q0)
            n += i
            iq[jz - 1] -= i << (24 - q0)
            ih = iq[jz - 1] >> (23 - q0)
        elif q0 == 0:
            ih = iq[jz - 1] >> 23
        elif z >= 0.5:
            ih = 2
        if ih > 0:
            n += 1
            carry = 0
            for i in range(jz):
                j = iq[i]
                if carry == 0:
                    if j != 0:
                        carry = 1
                        iq[i] = 0x1000000 - j
                else:
                    iq[i] = 0xFFFFFF - j
            if q0 > 0:
                iq[jz - 1] &= 0xFFFFFF >> q0
            if ih == 2:
                z = 1.0 - z
                if carry != 0:
                    z -= math.ldexp(1.0, q0)
        if z == 0.0:
            j = 0
            for i in range(jz - 1, jk - 1, -1):
                j |= iq[i]
            if j == 0:
                k = 1
                while iq[jk - k] == 0:
                    k += 1
                for i in range(jz + 1, jz + k + 1):
                    f[jx + i] = float(IPIO2[jv + i])
                    fw = 0.0
                    for j in range(jx + 1):
                        fw += x[j] * f[jx + i - j]
                    q[i] = fw
                jz += k
                continue
        break
    if z == 0.0:
        jz -= 1
        q0 -= 24
        while iq[jz] == 0:
            jz -= 1
            q0 -= 24
    else:
        z = math.ldexp(z, -q0)
        if z >= TWO24:
            fw = float(int(TWON24 * z))
            iq[jz] = int(z - TWO24 * fw)
            jz += 1
            q0 += 24
            iq[jz] = int(fw)
        else:
            iq[jz] = int(z)
    fw = math.ldexp(1.0, q0)
    for i in range(jz, -1, -1):
        q[i] = fw * float(iq[i])
        fw *= TWON24
    for i in range(jz, -1, -1):
        fw = 0.0
        for k in range(min(jk, jz - i) + 1):
            fw += PIO2[k] * q[i + k]
        fq[jz - i] = fw
    fw = 0.0
    for i in range(jz, -1, -1):
        fw += fq[i]
    y0 = fw if ih == 0 else -fw
    fw = fq[0] - fw
    for i in range(1, jz + 1):
        fw += fq[i]
    return n & 7, y0, fw if ih == 0 else -fw
