// LM float math algorithms v1: FreeBSD msun e_pow.c (ADR-057).
// Source: https://github.com/freebsd/freebsd-src/blob/main/lib/msun/src/e_pow.c
// Every arithmetic operation explicitly rounds to binary64 to prohibit FMA.
// Copyright (C) 2004 by Sun Microsystems, Inc. All rights reserved.
// Permission to use, copy, modify, and distribute this software is freely
// granted, provided that this notice is preserved.
package main

import "math"

func floatPowBits(x float64) int64     { return int64(math.Float64bits(x)) }
func floatPowFromBits(x int64) float64 { return math.Float64frombits(uint64(x)) }
func floatPowHigh(x float64) int64     { return int64(math.Float64bits(x) >> 32) }
func floatPowLowZero(x float64) float64 {
	return math.Float64frombits(math.Float64bits(x) & 0xffffffff00000000)
}

// The split logarithm, product and exponential retain msun's rounding order.
func floatMathPow(x, y float64) float64 {
	var i, ix, iy, j, k, n int64
	var ax, bp, dp_h, dp_l, p_h, p_l, r, s2, s_h, s_l, sign, ss, t, t1, t2, t_h, t_l, u, v, w, y1, z, z_h, z_l float64
	if (y == 0.0) || (x == 1.0) {
		return 1.0
	}
	if x == 0.0 {
		if y < 0.0 {
			return math.Inf(1)
		} else {
			return 0.0
		}
	}
	sign = 1.0
	if x < 0.0 {
		if y != math.Trunc(y) {
			return math.NaN()
		}
		if (math.Abs(y) < 9007199254740992.0) && ((int64(y) % 2) != 0) {
			sign = -(1.0)
		}
	}
	if y == 1.0 {
		return x
	}
	if y == -(1.0) {
		return float64(1.0 / x)
	}
	if y == 2.0 {
		return float64(x * x)
	}
	if (y == 0.5) && (x > 0.0) {
		return math.Sqrt(x)
	}
	ax = math.Abs(x)
	if ax == 1.0 {
		return sign
	}
	ix = floatPowHigh(ax)
	iy = floatPowHigh(math.Abs(y))
	if iy > 1105199104 {
		if iy > 1139802112 {
			if (ax < 1.0) == (y < 0.0) {
				return float64(sign * math.Inf(1))
			}
			return 0.0
		}
		if ix < 1072693247 {
			if y < 0.0 {
				return float64(sign * math.Inf(1))
			} else {
				return 0.0
			}
		}
		if ix > 1072693248 {
			if y > 0.0 {
				return float64(sign * math.Inf(1))
			} else {
				return 0.0
			}
		}
		t = float64(ax - 1.0)
		w = float64(float64(t*t) * float64(0.5-float64(t*float64(0.3333333333333333-float64(t*0.25)))))
		u = float64(1.4426950216293335 * t)
		v = float64(float64(t*1.9259629911266175e-08) - float64(w*1.4426950408889634))
		t1 = floatPowLowZero(float64(u + v))
		t2 = float64(v - float64(t1-u))
	} else {
		n = 0
		if ix < 1048576 {
			ax = float64(ax * 9007199254740992.0)
			n = (n - 53)
			ix = floatPowHigh(ax)
		}
		n = ((n + (ix >> 20)) - 1023)
		j = (ix & 1048575)
		ix = (j | 1072693248)
		k = 0
		if j > 235662 {
			if j < 767610 {
				k = 1
			} else {
				n = (n + 1)
				ix = (ix - 1048576)
			}
		}
		ax = floatPowFromBits(((ix << 32) | (floatPowBits(ax) & 4294967295)))
		if k == 0 {
			bp = 1.0
		} else {
			bp = 1.5
		}
		if k == 0 {
			dp_h = 0.0
		} else {
			dp_h = 0.5849624872207642
		}
		if k == 0 {
			dp_l = 0.0
		} else {
			dp_l = 1.350039202129749e-08
		}
		u = float64(ax - bp)
		v = float64(1.0 / float64(ax+bp))
		ss = float64(u * v)
		s_h = floatPowLowZero(ss)
		t_h = floatPowFromBits((((((ix >> 1) | 536870912) + 524288) + (k << 18)) << 32))
		t_l = float64(ax - float64(t_h-bp))
		s_l = float64(v * float64(float64(u-float64(s_h*t_h))-float64(s_h*t_l)))
		s2 = float64(ss * ss)
		r = float64(float64(s2*s2) * float64(0.5999999999999946+float64(s2*float64(0.4285714285785502+float64(s2*float64(0.33333332981837743+float64(s2*float64(0.272728123808534+float64(s2*float64(0.23066074577556175+float64(s2*0.20697501780033842)))))))))))
		r = float64(r + float64(s_l*float64(s_h+ss)))
		s2 = float64(s_h * s_h)
		t_h = floatPowLowZero(float64(float64(3.0+s2) + r))
		t_l = float64(r - float64(float64(t_h-3.0)-s2))
		u = float64(s_h * t_h)
		v = float64(float64(s_l*t_h) + float64(t_l*ss))
		p_h = floatPowLowZero(float64(u + v))
		p_l = float64(v - float64(p_h-u))
		z_h = float64(0.9617967009544373 * p_h)
		z_l = float64(float64(float64(-(7.028461650952758e-09)*p_h)+float64(p_l*0.9617966939259756)) + dp_l)
		t = float64(n)
		t1 = floatPowLowZero(float64(float64(float64(z_h+z_l)+dp_h) + t))
		t2 = float64(z_l - float64(float64(float64(t1-t)-dp_h)-z_h))
	}
	y1 = floatPowLowZero(y)
	p_l = float64(float64(float64(y-y1)*t1) + float64(y*t2))
	p_h = float64(y1 * t1)
	z = float64(p_l + p_h)
	if z >= 1024.0 {
		if (z > 1024.0) || (float64(p_l+8.008566259537294e-17) > float64(z-p_h)) {
			return float64(sign * math.Inf(1))
		}
	}
	if z <= -(1075.0) {
		if (z < -(1075.0)) || (p_l <= float64(z-p_h)) {
			return 0.0
		}
	}
	j = floatPowHigh(z)
	i = (j & 2147483647)
	k = ((i >> 20) - 1023)
	n = 0
	if i > 1071644672 {
		n = (j + (1048576 >> (k + 1)))
		k = (((n & 2147483647) >> 20) - 1023)
		t = floatPowFromBits(((n & ^(1048575 >> k)) << 32))
		n = (((n & 1048575) | 1048576) >> (20 - k))
		if z < 0.0 {
			n = -(n)
		}
		p_h = float64(p_h - t)
	}
	t = floatPowLowZero(float64(p_l + p_h))
	u = float64(t * 0.6931471824645996)
	v = float64(float64(float64(p_l-float64(t-p_h))*0.6931471805599453) + float64(t*-(1.904654299957768e-09)))
	z = float64(u + v)
	w = float64(v - float64(z-u))
	t = float64(z * z)
	t1 = float64(z - float64(t*float64(0.16666666666666602+float64(t*float64(-(0.0027777777777015593)+float64(t*float64(6.613756321437934e-05+float64(t*float64(-(1.6533902205465252e-06)+float64(t*4.1381367970572385e-08))))))))))
	r = float64(float64(float64(z*t1)/float64(t1-2.0)) - float64(w+float64(z*w)))
	z = float64(1.0 - float64(r-z))
	return float64(sign * math.Ldexp(z, int(n)))
}

func prim_float_pow(x, y Value) Value {
	f, g := x.(float64), y.(float64)
	r := floatMathPow(f, g)
	if math.IsInf(r, 0) || math.IsNaN(r) {
		numFault("E-FLOAT", "float.pow", []Value{f, g}, -1, false)
	}
	return normZero(r)
}
