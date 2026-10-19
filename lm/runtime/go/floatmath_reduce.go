// LM float math algorithms v1 (ADR-057).
// Source: https://github.com/freebsd/freebsd-src/tree/main/lib/msun/src
// Retrieved 2026-10-18; the port below pins the algorithm and constants.
// FreeBSD msun e_rem_pio2.c, optimized by Bruce D. Evans.
// Copyright (C) 1993 by Sun Microsystems, Inc. All rights reserved.
// Developed at SunSoft, a Sun Microsystems, Inc. business.
// Permission to use, copy, modify, and distribute this software is freely
// granted, provided that this notice is preserved.
package main

import "math"

func floatMathRemPio2(x float64) (int32, float64, float64) {
	const (
		invpio2 = 6.36619772367581382433e-01
		p1      = 1.57079632673412561417e+00
		p1t     = 6.07710050650619224932e-11
		p2      = 6.07710050630396597660e-11
		p2t     = 2.02226624879595063154e-21
		p3      = 2.02226624871116645580e-21
		p3t     = 8.47842766036889956997e-32
	)
	hx := int32(math.Float64bits(x) >> 32)
	ix := hx & 0x7fffffff
	var n int32
	if ix <= 0x400f6a7a {
		if ix&0xfffff != 0x921fb {
			n = 2
			if ix <= 0x4002d97c {
				n = 1
			}
		}
	} else if ix <= 0x401c463b {
		if ix <= 0x4015fdbc {
			if ix != 0x4012d97c {
				n = 3
			}
		} else if ix != 0x401921fb {
			n = 4
		}
	}
	if n != 0 {
		if hx < 0 {
			n = -n
		}
		z := float64(x - float64(float64(n)*p1))
		w := float64(float64(n) * p1t)
		a := float64(z - w)
		return n, a, float64(float64(z-a) - w)
	}
	if ix < 0x413921fb {
		fn := math.RoundToEven(float64(x * invpio2))
		n = int32(fn)
		r := float64(x - float64(fn*p1))
		w := float64(fn * p1t)
		a := float64(r - w)
		j := ix >> 20
		i := j - int32((math.Float64bits(a)>>52)&0x7ff)
		if i > 16 {
			t := r
			w = float64(fn * p2)
			r = float64(t - w)
			w = float64(float64(fn*p2t) - float64(float64(t-r)-w))
			a = float64(r - w)
			i = j - int32((math.Float64bits(a)>>52)&0x7ff)
			if i > 49 {
				t = r
				w = float64(fn * p3)
				r = float64(t - w)
				w = float64(float64(fn*p3t) - float64(float64(t-r)-w))
				a = float64(r - w)
			}
		}
		return n, a, float64(float64(r-a) - w)
	}
	if ix >= 0x7ff00000 {
		return 0, float64(x - x), float64(x - x)
	}
	e0 := (ix >> 20) - 1046
	z := math.Float64frombits(uint64(uint32(ix-(e0<<20)))<<32 | (math.Float64bits(x) & 0xffffffff))
	tx := [3]float64{}
	for i := int32(0); i < 2; i++ {
		tx[i] = float64(int32(z))
		z = float64(float64(z-tx[i]) * 0x1p24)
	}
	tx[2] = z
	nx := int32(3)
	for tx[nx-1] == 0 {
		nx--
	}
	n, a, b := floatMathKernelRemPio2(tx[:nx], e0)
	if hx < 0 {
		return -n, -a, -b
	}
	return n, a, b
}
