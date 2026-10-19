// LM float math algorithms v1: FreeBSD msun inverse trigonometry (ADR-057).
// Source: https://github.com/freebsd/freebsd-src/tree/main/lib/msun/src
// Ports of e_asin.c, e_acos.c, s_atan.c, e_atan2.c; binary64 C order.
// Copyright (C) 1993 by Sun Microsystems, Inc. All rights reserved.
// Developed at SunSoft (asin/acos/atan2) and SunPro (atan),
// Sun Microsystems, Inc. businesses.
// Permission to use, copy, modify, and distribute this software is freely
// granted, provided that this notice is preserved.
package main

import "math"

const (
	floatMathPio2Hi float64 = 1.57079632679489655800e+00
	floatMathPio2Lo float64 = 6.12323399573676603587e-17
	floatMathPio4Hi float64 = 7.85398163397448278999e-01
	floatMathPi     float64 = 3.14159265358979311600e+00
	floatMathPiLo   float64 = 1.2246467991473531772e-16
)

func floatMathAsinRatio(z float64) float64 {
	p := float64(z * float64(0.16666666666666666+float64(z*float64(float64(-0.3255658186224009)+float64(z*float64(0.20121253213486293+float64(z*float64(float64(-0.04005553450067941)+float64(z*float64(0.0007915349942898145+float64(z*3.479331075960212e-05)))))))))))
	q := float64(1.0 + float64(z*float64(float64(-2.403394911734414)+float64(z*float64(2.0209457602335057+float64(z*float64(float64(-0.6882839716054533)+float64(z*0.07703815055590194))))))))
	return float64(p / q)
}

func floatMathAsin(x float64) float64 {
	ix := uint32(math.Float64bits(x)>>32) & 0x7fffffff
	if math.Abs(x) >= 1 {
		if math.Abs(x) == 1 {
			return float64(float64(x*floatMathPio2Hi) + float64(x*floatMathPio2Lo))
		}
		return math.NaN()
	}
	if ix < 0x3fe00000 {
		if ix < 0x3e400000 {
			return x
		}
		return float64(x + float64(x*floatMathAsinRatio(float64(x*x))))
	}
	t := float64(float64(1-math.Abs(x)) * 0.5)
	r := floatMathAsinRatio(t)
	s := math.Sqrt(t)
	if ix >= 0x3fef3333 {
		t = float64(floatMathPio2Hi - float64(float64(2*float64(s+float64(s*r)))-floatMathPio2Lo))
	} else {
		w := math.Float64frombits(math.Float64bits(s) & 0xffffffff00000000)
		c := float64(float64(t-float64(w*w)) / float64(s+w))
		p := float64(float64(float64(2*s)*r) - float64(floatMathPio2Lo-float64(2*c)))
		q := float64(floatMathPio4Hi - float64(2*w))
		t = float64(floatMathPio4Hi - float64(p-q))
	}
	if x < 0 {
		return float64(-t)
	}
	return t
}

func floatMathAcos(x float64) float64 {
	ix := uint32(math.Float64bits(x)>>32) & 0x7fffffff
	if math.Abs(x) >= 1 {
		if x == 1 {
			return 0
		}
		if x == -1 {
			return float64(floatMathPi + float64(2*floatMathPio2Lo))
		}
		return math.NaN()
	}
	if ix < 0x3fe00000 {
		if ix <= 0x3c600000 {
			return float64(floatMathPio2Hi + floatMathPio2Lo)
		}
		r := floatMathAsinRatio(float64(x * x))
		return float64(floatMathPio2Hi - float64(x-float64(floatMathPio2Lo-float64(x*r))))
	}
	if x < 0 {
		z := float64(float64(1+x) * 0.5)
		s := math.Sqrt(z)
		w := float64(float64(floatMathAsinRatio(z)*s) - floatMathPio2Lo)
		return float64(floatMathPi - float64(2*float64(s+w)))
	}
	z := float64(float64(1-x) * 0.5)
	s := math.Sqrt(z)
	df := math.Float64frombits(math.Float64bits(s) & 0xffffffff00000000)
	c := float64(float64(z-float64(df*df)) / float64(s+df))
	w := float64(float64(floatMathAsinRatio(z)*s) + c)
	return float64(2 * float64(df+w))
}

func floatMathAtan(x float64) float64 {
	if math.IsInf(x, 0) || math.IsNaN(x) {
		return math.NaN()
	}
	ix := uint32(math.Float64bits(x)>>32) & 0x7fffffff
	negative := x < 0
	if ix >= 0x44100000 {
		if negative {
			return float64(float64(-floatMathPio2Hi) - floatMathPio2Lo)
		}
		return float64(floatMathPio2Hi + floatMathPio2Lo)
	}
	ident := -1
	if ix < 0x3fdc0000 {
		if ix < 0x3e400000 {
			return x
		}
	} else {
		x = math.Abs(x)
		if ix < 0x3fe60000 {
			ident, x = 0, float64(float64(float64(2*x)-1)/float64(2+x))
		} else if ix < 0x3ff30000 {
			ident, x = 1, float64(float64(x-1)/float64(x+1))
		} else if ix < 0x40038000 {
			ident, x = 2, float64(float64(x-1.5)/float64(1+float64(1.5*x)))
		} else {
			ident, x = 3, float64(-1/x)
		}
	}
	atanHi := [...]float64{0.4636476090008061, floatMathPio4Hi, 0.982793723247329, floatMathPio2Hi}
	atanLo := [...]float64{2.2698777452961687e-17, 3.061616997868383e-17, 1.3903311031230998e-17, floatMathPio2Lo}
	AT := [...]float64{0.3333333333333293, float64(-0.19999999999876483), 0.14285714272503466, float64(-0.11111110405462356), 0.09090887133436507, float64(-0.0769187620504483), 0.06661073137387531, float64(-0.058335701337905735), 0.049768779946159324, float64(-0.036531572744216916), 0.016285820115365782}

	z := float64(x * x)
	w := float64(z * z)
	s1 := float64(z * float64(AT[0]+float64(w*float64(AT[2]+float64(w*float64(AT[4]+float64(w*float64(AT[6]+float64(w*float64(AT[8]+float64(w*AT[10])))))))))))
	s2 := float64(w * float64(AT[1]+float64(w*float64(AT[3]+float64(w*float64(AT[5]+float64(w*float64(AT[7]+float64(w*AT[9])))))))))
	if ident < 0 {
		return float64(x - float64(x*float64(s1+s2)))
	}
	z = float64(atanHi[ident] - float64(float64(float64(x*float64(s1+s2))-atanLo[ident])-x))
	if negative {
		return float64(-z)
	}
	return z
}

func floatMathAtan2(y, x float64) float64 {
	// Finite LM inputs, with LM's normalization of signed zero.
	if math.IsInf(x, 0) || math.IsNaN(x) || math.IsInf(y, 0) || math.IsNaN(y) {
		return math.NaN()
	}
	if x == 0 {
		x = 0
	}
	if y == 0 {
		y = 0
	}
	if x == 1 {
		return floatMathAtan(y)
	}
	if y == 0 {
		if x < 0 {
			return floatMathPi
		}
		return 0
	}
	if x == 0 {
		if y < 0 {
			return float64(-floatMathPio2Hi)
		}
		return floatMathPio2Hi
	}
	ix := int32(math.Float64bits(x)>>32) & 0x7fffffff
	iy := int32(math.Float64bits(y)>>32) & 0x7fffffff
	m := 0
	if x < 0 {
		m += 2
	}
	if y < 0 {
		m++
	}
	k := (iy - ix) >> 20
	var z float64
	if k > 60 {
		z = float64(floatMathPio2Hi + float64(0.5*floatMathPiLo))
		m &= 1
	} else if x < 0 && k < -60 {
		z = 0
	} else {
		z = floatMathAtan(math.Abs(float64(y / x)))
	}
	switch m {
	case 0:
		return z
	case 1:
		return float64(-z)
	case 2:
		return float64(floatMathPi - float64(z-floatMathPiLo))
	default:
		return float64(float64(z-floatMathPiLo) - floatMathPi)
	}
}

func prim_float_asin(x Value) Value { return floatMathPrim("float.asin", x, floatMathAsin, false) }
func prim_float_acos(x Value) Value { return floatMathPrim("float.acos", x, floatMathAcos, false) }
func prim_float_atan(x Value) Value { return floatMathPrim("float.atan", x, floatMathAtan, false) }
func prim_float_atan2(y, x Value) Value {
	f, g := y.(float64), x.(float64)
	r := floatMathAtan2(f, g)
	if math.IsInf(r, 0) || math.IsNaN(r) {
		numFault("E-FLOAT", "float.atan2", []Value{f, g}, -1, false)
	}
	return normZero(r)
}
