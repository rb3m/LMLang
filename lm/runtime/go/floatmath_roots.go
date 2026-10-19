// LM float math algorithms v1: FreeBSD msun s_cbrt.c and e_hypot.c.
// Sources: https://github.com/freebsd/freebsd-src/blob/main/lib/msun/src/s_cbrt.c
// https://github.com/JuliaMath/openlibm/blob/master/src/e_hypot.c
// (FreeBSD e_hypot.c revision 1.14). No platform transcendentals.
// Every arithmetic step explicitly rounds to binary64 to prohibit FMA.
// Copyright (C) 1993 by Sun Microsystems, Inc. All rights reserved.
// Developed at SunPro (s_cbrt.c) and SunSoft (e_hypot.c), Sun Microsystems,
// Inc. businesses. Permission to use, copy, modify, and distribute this
// software is freely granted, provided that this notice is preserved.
// s_cbrt.c optimized by Bruce D. Evans.
package main

import "math"

func floatMathCbrt(x float64) float64 {
	bits := math.Float64bits(x)
	sign := bits & (uint64(1) << 63)
	hx := (bits >> 32) & 0x7fffffff
	if hx >= 0x7ff00000 || x == 0 {
		return x
	}
	var t float64
	if hx < 0x00100000 {
		high := (math.Float64bits(float64(x*0x1p54)) >> 32) & 0x7fffffff
		t = math.Float64frombits(sign | ((high/3 + 696219795) << 32))
	} else {
		t = math.Float64frombits(sign | ((hx/3 + 715094163) << 32))
	}
	const (
		p0 = 1.87595182427177009643
		p1 = -1.88497979543377169875
		p2 = 1.621429720105354466140
		p3 = -0.758397934778766047437
		p4 = 0.145996192886612446982
	)
	r := float64(float64(t*t) * float64(t/x))
	u := float64(p0 + float64(r*float64(p1+float64(r*p2))))
	v := float64(float64(float64(r*r)*r) * float64(p3+float64(r*p4)))
	t = float64(t * float64(u+v))
	t = math.Float64frombits((math.Float64bits(t) + 0x80000000) & 0xffffffffc0000000)
	s := float64(t * t)
	r = float64(x / s)
	w := float64(t + t)
	r = float64(float64(r-t) / float64(w+r))
	return float64(t + float64(t*r))
}

func floatMathHypot(x, y float64) float64 {
	a, b := math.Abs(x), math.Abs(y)
	ha, hb := math.Float64bits(a)>>32, math.Float64bits(b)>>32
	if hb > ha {
		a, b, ha, hb = b, a, hb, ha
	}
	if ha-hb > 0x3c00000 {
		return float64(a + b)
	}
	k := 0
	if ha > 0x5f300000 {
		if ha >= 0x7ff00000 {
			return float64(a + b)
		}
		a = float64(a * 0x1p-600)
		b = float64(b * 0x1p-600)
		ha -= 0x25800000
		hb -= 0x25800000
		k = 600
	}
	if hb < 0x20b00000 {
		if hb <= 0x000fffff {
			if b == 0 {
				return a
			}
			a = float64(a * 0x1p1022)
			b = float64(b * 0x1p1022)
			k -= 1022
		} else {
			a = float64(a * 0x1p600)
			b = float64(b * 0x1p600)
			ha += 0x25800000
			hb += 0x25800000
			k -= 600
		}
	}
	w := float64(a - b)
	if w > b {
		t1 := math.Float64frombits(ha << 32)
		t2 := float64(a - t1)
		w = math.Sqrt(float64(float64(t1*t1) - float64(float64(b*(-b))-float64(t2*float64(a+t1)))))
	} else {
		a = float64(a + a)
		y1 := math.Float64frombits(hb << 32)
		y2 := float64(b - y1)
		t1 := math.Float64frombits((ha + 0x00100000) << 32)
		t2 := float64(a - t1)
		w = math.Sqrt(float64(float64(t1*y1) - float64(float64(w*(-w))-float64(float64(t1*y2)+float64(t2*b)))))
	}
	if k != 0 {
		return float64(math.Ldexp(1, k) * w)
	}
	return w
}

func prim_float_cbrt(x Value) Value { return floatMathPrim("float.cbrt", x, floatMathCbrt, false) }

func prim_float_hypot(x, y Value) Value {
	f, g := x.(float64), y.(float64)
	r := floatMathHypot(f, g)
	if math.IsInf(r, 0) || math.IsNaN(r) {
		numFault("E-FLOAT", "float.hypot", []Value{f, g}, -1, false)
	}
	return normZero(r)
}
