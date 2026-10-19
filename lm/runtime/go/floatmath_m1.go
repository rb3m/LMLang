// LM float math algorithms v1: FreeBSD msun s_log1p.c/s_expm1.c.
// Sources: https://web.mit.edu/freebsd/head/lib/msun/src/s_log1p.c
// (FreeBSD revision 251292, 2013-06-03)
// https://raw.githubusercontent.com/freebsd/freebsd-src/main/lib/msun/src/s_expm1.c
// Preserve msun's word thresholds, reduction and evaluation order; every
// arithmetic step explicitly rounds to binary64 to prohibit FMA.
// Copyright (C) 1993 by Sun Microsystems, Inc. All rights reserved.
// Developed at SunPro, a Sun Microsystems, Inc. business.
// Permission to use, copy, modify, and distribute this software is freely
// granted, provided that this notice is preserved.
package main

import "math"

func floatMathLog1p(x float64) float64 {
	if x <= -1 {
		return math.NaN()
	}
	if math.IsInf(x, 0) || math.IsNaN(x) {
		return x
	}
	hx := int32(math.Float64bits(x) >> 32)
	ax := uint32(hx) & 0x7fffffff
	k, c := 1, 0.0
	var f float64
	var hu uint32
	if hx < 0x3fda827a {
		if ax < 0x3e200000 {
			if ax < 0x3c900000 {
				return x
			}
			return float64(x - float64(float64(x*x)*0.5))
		}
		if hx > 0 || hx <= -1076707644 { // int32(0xbfd2bec4)
			k, f, hu = 0, x, 1
		}
	}
	if k != 0 {
		var u float64
		if hx < 0x43400000 {
			u = float64(1 + x)
			hu = uint32(math.Float64bits(u) >> 32)
			k = int(hu>>20) - 1023
			if k > 0 {
				c = float64(1 - float64(u-x))
			} else {
				c = float64(x - float64(u-1))
			}
			c = float64(c / u)
		} else {
			u = x
			hu = uint32(math.Float64bits(u) >> 32)
			k = int(hu>>20) - 1023
		}
		hu &= 0xfffff
		low := math.Float64bits(u) & 0xffffffff
		if hu < 0x6a09e {
			u = math.Float64frombits(uint64(hu|0x3ff00000)<<32 | low)
		} else {
			k++
			u = math.Float64frombits(uint64(hu|0x3fe00000)<<32 | low)
			hu = (0x100000 - hu) >> 2
		}
		f = float64(u - 1)
	}
	hfsq := float64(float64(0.5*f) * f)
	kf := float64(k)
	if hu == 0 {
		if f == 0 {
			if k == 0 {
				return 0
			}
			c = float64(c + float64(kf*lmLn2Lo))
			return float64(float64(kf*lmLn2Hi) + c)
		}
		r := float64(hfsq * float64(1-float64(0.66666666666666666*f)))
		if k == 0 {
			return float64(f - r)
		}
		return float64(float64(kf*lmLn2Hi) - float64(float64(r-float64(float64(kf*lmLn2Lo)+c))-f))
	}
	s := float64(f / float64(2+f))
	z := float64(s * s)
	p := float64(1.531383769920937332e-01 + float64(z*1.479819860511658591e-01))
	p = float64(1.818357216161805012e-01 + float64(z*p))
	p = float64(2.222219843214978396e-01 + float64(z*p))
	p = float64(2.857142874366239149e-01 + float64(z*p))
	p = float64(3.999999999940941908e-01 + float64(z*p))
	r := float64(z * float64(6.666666666666735130e-01+float64(z*p)))
	if k == 0 {
		return float64(f - float64(hfsq-float64(s*float64(hfsq+r))))
	}
	return float64(float64(kf*lmLn2Hi) - float64(float64(hfsq-float64(float64(s*float64(hfsq+r))+float64(float64(kf*lmLn2Lo)+c)))-f))
}

func floatMathExpm1(x float64) float64 {
	if math.IsInf(x, 0) || math.IsNaN(x) {
		return math.NaN()
	}
	hx := uint32(math.Float64bits(x)>>32) & 0x7fffffff
	if hx >= 0x4043687a {
		if x > 7.09782712893383973096e+02 {
			return math.Inf(1)
		}
		if x < 0 {
			return -1
		}
	}
	k, c := 0, 0.0
	if hx > 0x3fd62e42 {
		var hi, lo float64
		if hx < 0x3ff0a2b2 {
			if x > 0 {
				hi, lo, k = float64(x-lmLn2Hi), lmLn2Lo, 1
			} else {
				hi, lo, k = float64(x+lmLn2Hi), -lmLn2Lo, -1
			}
		} else {
			if x > 0 {
				k = int(float64(float64(lmInvLn2*x) + 0.5))
			} else {
				k = int(float64(float64(lmInvLn2*x) - 0.5))
			}
			t := float64(k)
			hi = float64(x - float64(t*lmLn2Hi))
			lo = float64(t * lmLn2Lo)
		}
		x = float64(hi - lo)
		c = float64(float64(hi-x) - lo)
	} else if hx < 0x3c900000 {
		return x
	}
	hfx := float64(0.5 * x)
	hxs := float64(x * hfx)
	p := float64(4.00821782732936239552e-06 + float64(hxs*-2.01099218183624371326e-07))
	p = float64(-7.93650757867487942473e-05 + float64(hxs*p))
	p = float64(1.58730158725481460165e-03 + float64(hxs*p))
	p = float64(-3.33333333333331316428e-02 + float64(hxs*p))
	r1 := float64(1 + float64(hxs*p))
	t := float64(3 - float64(r1*hfx))
	e := float64(hxs * float64(float64(r1-t)/float64(6-float64(x*t))))
	if k == 0 {
		return float64(x - float64(float64(x*e)-hxs))
	}
	e = float64(float64(float64(x*float64(e-c))-c) - hxs)
	if k == -1 {
		return float64(float64(0.5*float64(x-e)) - 0.5)
	}
	if k == 1 {
		if x < -0.25 {
			return float64(-2 * float64(e-float64(x+0.5)))
		}
		return float64(1 + float64(2*float64(x-e)))
	}
	if k <= -2 || k > 56 {
		y := float64(1 - float64(e-x))
		if k == 1024 {
			y = float64(float64(y*2) * 0x1p1023)
		} else {
			y = float64(y * math.Float64frombits(uint64(1023+k)<<52))
		}
		return float64(y - 1)
	}
	var y float64
	if k < 20 {
		t = math.Float64frombits(uint64(0x3ff00000-(0x200000>>uint(k))) << 32)
		y = float64(t - float64(e-x))
	} else {
		t = math.Float64frombits(uint64(1023-k) << 52)
		y = float64(float64(x-float64(e+t)) + 1)
	}
	return float64(y * math.Float64frombits(uint64(1023+k)<<52))
}
