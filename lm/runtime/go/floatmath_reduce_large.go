// LM float math algorithms v1 (ADR-057).
// Source: https://github.com/freebsd/freebsd-src/tree/main/lib/msun/src
// Retrieved 2026-10-18; the port below pins the algorithm and constants.
// FreeBSD msun k_rem_pio2.c, specialized to binary64 (prec=1, jk=4).
// Copyright (C) 1993 by Sun Microsystems, Inc. All rights reserved.
// Developed at SunSoft, a Sun Microsystems, Inc. business.
// Permission to use, copy, modify, and distribute this software is freely
// granted, provided that this notice is preserved.
package main

import "math"

// 24-bit chunks of 2/pi; 66 chunks suffice for every binary64 exponent.
var floatMathIPio2 = [...]int32{
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
}
var floatMathPio2 = [...]float64{
	1.57079625129699707031e+00, 7.54978941586159635335e-08,
	5.39030252995776476554e-15, 3.28200341580791294123e-22,
	1.27065575308067607349e-29, 1.22933308981111328932e-36,
	2.73370053816464559624e-44, 2.16741683877804819444e-51,
}

func floatMathKernelRemPio2(x []float64, e0 int32) (int32, float64, float64) {
	const jk int32 = 4
	var iq [20]int32
	var f, fq, q [20]float64
	jx := int32(len(x)) - 1
	jv := (e0 - 3) / 24
	if jv < 0 {
		jv = 0
	}
	q0 := e0 - 24*(jv+1)
	j := jv - jx
	for i := int32(0); i <= jx+jk; i++ {
		if j >= 0 {
			f[i] = float64(floatMathIPio2[j])
		}
		j++
	}
	for i := int32(0); i <= jk; i++ {
		fw := 0.0
		for j := int32(0); j <= jx; j++ {
			fw = float64(fw + float64(x[j]*f[jx+i-j]))
		}
		q[i] = fw
	}
	jz := jk
	var z float64
	var n, ih int32
	for {
		z = q[jz]
		for i, j := int32(0), jz; j > 0; i, j = i+1, j-1 {
			fw := float64(int32(float64(0x1p-24 * z)))
			iq[i] = int32(float64(z - float64(0x1p24*fw)))
			z = float64(q[j-1] + fw)
		}
		z = math.Ldexp(z, int(q0))
		z = float64(z - float64(8*math.Floor(float64(z*0.125))))
		n = int32(z)
		z = float64(z - float64(n))
		ih = 0
		if q0 > 0 {
			i := iq[jz-1] >> (24 - q0)
			n += i
			iq[jz-1] -= i << (24 - q0)
			ih = iq[jz-1] >> (23 - q0)
		} else if q0 == 0 {
			ih = iq[jz-1] >> 23
		} else if z >= 0.5 {
			ih = 2
		}
		if ih > 0 {
			n++
			carry := int32(0)
			for i := int32(0); i < jz; i++ {
				j := iq[i]
				if carry == 0 {
					if j != 0 {
						carry = 1
						iq[i] = 0x1000000 - j
					}
				} else {
					iq[i] = 0xffffff - j
				}
			}
			if q0 == 1 {
				iq[jz-1] &= 0x7fffff
			}
			if q0 == 2 {
				iq[jz-1] &= 0x3fffff
			}
			if ih == 2 {
				z = float64(1 - z)
				if carry != 0 {
					z = float64(z - math.Ldexp(1, int(q0)))
				}
			}
		}
		if z == 0 {
			j := int32(0)
			for i := jz - 1; i >= jk; i-- {
				j |= iq[i]
			}
			if j == 0 {
				k := int32(1)
				for iq[jk-k] == 0 {
					k++
				}
				for i := jz + 1; i <= jz+k; i++ {
					f[jx+i] = float64(floatMathIPio2[jv+i])
					fw := 0.0
					for j := int32(0); j <= jx; j++ {
						fw = float64(fw + float64(x[j]*f[jx+i-j]))
					}
					q[i] = fw
				}
				jz += k
				continue
			}
		}
		break
	}
	if z == 0 {
		jz--
		q0 -= 24
		for iq[jz] == 0 {
			jz--
			q0 -= 24
		}
	} else {
		z = math.Ldexp(z, int(-q0))
		if z >= 0x1p24 {
			fw := float64(int32(float64(0x1p-24 * z)))
			iq[jz] = int32(float64(z - float64(0x1p24*fw)))
			jz++
			q0 += 24
			iq[jz] = int32(fw)
		} else {
			iq[jz] = int32(z)
		}
	}
	fw := math.Ldexp(1, int(q0))
	for i := jz; i >= 0; i-- {
		q[i] = float64(fw * float64(iq[i]))
		fw = float64(fw * 0x1p-24)
	}
	for i := jz; i >= 0; i-- {
		fw = 0
		for k := int32(0); k <= jk && k <= jz-i; k++ {
			fw = float64(fw + float64(floatMathPio2[k]*q[i+k]))
		}
		fq[jz-i] = fw
	}
	fw = 0
	for i := jz; i >= 0; i-- {
		fw = float64(fw + fq[i])
	}
	a := fw
	fw = float64(fq[0] - fw)
	for i := int32(1); i <= jz; i++ {
		fw = float64(fw + fq[i])
	}
	if ih != 0 {
		return n & 7, -a, -fw
	}
	return n & 7, a, fw
}
