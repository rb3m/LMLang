// LM float math algorithms v1 (ADR-057).
// Source: https://github.com/freebsd/freebsd-src/tree/main/lib/msun/src
// Retrieved 2026-10-18; the port below pins the algorithm and constants.
// FreeBSD msun s_sin.c, s_cos.c, s_tan.c, k_sin.c, k_cos.c, k_tan.c.
// Copyright (C) 1993 by Sun Microsystems, Inc. All rights reserved.
// s_sin.c/s_cos.c/s_tan.c: Developed at SunPro, a Sun Microsystems, Inc. business.
// k_sin.c/k_cos.c: Developed at SunSoft, a Sun Microsystems, Inc. business.
// k_tan.c: Copyright 2004 Sun Microsystems, Inc. All Rights Reserved.
// Permission to use, copy, modify, and distribute this software is freely
// granted, provided that this notice is preserved.
package main

import "math"

func floatMathSin(x float64) float64 {
	ix := int32(math.Float64bits(x)>>32) & 0x7fffffff
	if ix <= 0x3fe921fb {
		if ix < 0x3e500000 {
			return x
		}
		return floatMathKernelSin(x, 0, false)
	}
	if ix >= 0x7ff00000 {
		return float64(x - x)
	}
	n, a, b := floatMathRemPio2(x)
	switch n & 3 {
	case 0:
		return floatMathKernelSin(a, b, true)
	case 1:
		return floatMathKernelCos(a, b)
	case 2:
		return -floatMathKernelSin(a, b, true)
	default:
		return -floatMathKernelCos(a, b)
	}
}

func floatMathCos(x float64) float64 {
	ix := int32(math.Float64bits(x)>>32) & 0x7fffffff
	if ix <= 0x3fe921fb {
		if ix < 0x3e46a09e {
			return 1
		}
		return floatMathKernelCos(x, 0)
	}
	if ix >= 0x7ff00000 {
		return float64(x - x)
	}
	n, a, b := floatMathRemPio2(x)
	switch n & 3 {
	case 0:
		return floatMathKernelCos(a, b)
	case 1:
		return -floatMathKernelSin(a, b, true)
	case 2:
		return -floatMathKernelCos(a, b)
	default:
		return floatMathKernelSin(a, b, true)
	}
}

func floatMathTan(x float64) float64 {
	ix := int32(math.Float64bits(x)>>32) & 0x7fffffff
	if ix <= 0x3fe921fb {
		if ix < 0x3e400000 {
			return x
		}
		return floatMathKernelTan(x, 0, 1)
	}
	if ix >= 0x7ff00000 {
		return float64(x - x)
	}
	n, a, b := floatMathRemPio2(x)
	return floatMathKernelTan(a, b, 1-((n&1)<<1))
}

func floatMathKernelSin(x, y float64, tail bool) float64 {
	const (
		s1 = -1.66666666666666324348e-01
		s2 = 8.33333333332248946124e-03
		s3 = -1.98412698298579493134e-04
		s4 = 2.75573137070700676789e-06
		s5 = -2.50507602534068634195e-08
		s6 = 1.58969099521155010221e-10
	)
	z := float64(x * x)
	w := float64(z * z)
	r := float64(float64(s2+float64(z*float64(s3+float64(z*s4)))) + float64(float64(z*w)*float64(s5+float64(z*s6))))
	v := float64(z * x)
	if !tail {
		return float64(x + float64(v*float64(s1+float64(z*r))))
	}
	return float64(x - float64(float64(float64(z*float64(float64(0.5*y)-float64(v*r)))-y)-float64(v*s1)))
}

func floatMathKernelCos(x, y float64) float64 {
	const (
		c1 = 4.16666666666666019037e-02
		c2 = -1.38888888888741095749e-03
		c3 = 2.48015872894767294178e-05
		c4 = -2.75573143513906633035e-07
		c5 = 2.08757232129817482790e-09
		c6 = -1.13596475577881948265e-11
	)
	z := float64(x * x)
	w := float64(z * z)
	r := float64(float64(z*float64(c1+float64(z*float64(c2+float64(z*c3))))) + float64(float64(w*w)*float64(c4+float64(z*float64(c5+float64(z*c6))))))
	hz := float64(0.5 * z)
	w = float64(1 - hz)
	return float64(w + float64(float64(float64(1-w)-hz)+float64(float64(z*r)-float64(x*y))))
}

func floatMathKernelTan(x, y float64, iy int32) float64 {
	t := [...]float64{
		3.33333333333334091986e-01, 1.33333333333201242699e-01,
		5.39682539762260521377e-02, 2.18694882948595424599e-02,
		8.86323982359930005737e-03, 3.59207910759131235356e-03,
		1.45620945432529025516e-03, 5.88041240820264096874e-04,
		2.46463134818469906812e-04, 7.81794442939557092300e-05,
		7.14072491382608190305e-05, -1.85586374855275456654e-05,
		2.59073051863633712884e-05,
	}
	hx := int32(math.Float64bits(x) >> 32)
	ix := hx & 0x7fffffff
	if ix >= 0x3fe59428 {
		if hx < 0 {
			x = -x
			y = -y
		}
		z := float64(7.85398163397448278999e-01 - x)
		w := float64(3.06161699786838301793e-17 - y)
		x = float64(z + w)
		y = 0
	}
	z := float64(x * x)
	w := float64(z * z)
	r := float64(t[9] + float64(w*t[11]))
	r = float64(t[7] + float64(w*r))
	r = float64(t[5] + float64(w*r))
	r = float64(t[3] + float64(w*r))
	r = float64(t[1] + float64(w*r))
	v := float64(t[10] + float64(w*t[12]))
	v = float64(t[8] + float64(w*v))
	v = float64(t[6] + float64(w*v))
	v = float64(t[4] + float64(w*v))
	v = float64(z * float64(t[2]+float64(w*v)))
	s := float64(z * x)
	r = float64(y + float64(z*float64(float64(s*float64(r+v))+y)))
	r = float64(r + float64(t[0]*s))
	w = float64(x + r)
	if ix >= 0x3fe59428 {
		v = float64(iy)
		return float64(float64(1-((hx>>30)&2)) * float64(v-float64(2*float64(x-float64(float64(float64(w*w)/float64(w+v))-r)))))
	}
	if iy == 1 {
		return w
	}
	z = math.Float64frombits(math.Float64bits(w) & 0xffffffff00000000)
	v = float64(r - float64(z-x))
	a := float64(-1 / w)
	tt := math.Float64frombits(math.Float64bits(a) & 0xffffffff00000000)
	s = float64(1 + float64(tt*z))
	return float64(tt + float64(a*float64(s+float64(tt*v))))
}

func prim_float_sin(x Value) Value { return floatMathPrim("float.sin", x, floatMathSin, false) }
func prim_float_cos(x Value) Value { return floatMathPrim("float.cos", x, floatMathCos, false) }
func prim_float_tan(x Value) Value { return floatMathPrim("float.tan", x, floatMathTan, false) }
