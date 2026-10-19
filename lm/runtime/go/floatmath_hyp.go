// LM float math algorithms v1: FreeBSD msun e_sinh.c/e_cosh.c/s_tanh.c/k_exp.c.
// https://github.com/freebsd/freebsd-src/tree/main/lib/msun/src
// Every floating arithmetic step rounds explicitly to binary64 (no FMA).
// Copyright (C) 1993 by Sun Microsystems, Inc. All rights reserved.
// Developed at SunSoft (sinh/cosh) and SunPro (tanh), Sun Microsystems,
// Inc. businesses. Permission to use, copy, modify, and distribute this
// software is freely granted, provided that this notice is preserved.
//
// k_exp.c: Copyright (c) 2011 David Schultz <das@FreeBSD.ORG>
// All rights reserved.
// Redistribution and use in source and binary forms, with or without
// modification, are permitted provided that the following conditions
// are met:
//  1. Redistributions of source code must retain the above copyright
//     notice, this list of conditions and the following disclaimer.
//  2. Redistributions in binary form must reproduce the above copyright
//     notice, this list of conditions and the following disclaimer in the
//     documentation and/or other materials provided with the distribution.
//
// THIS SOFTWARE IS PROVIDED BY THE AUTHOR AND CONTRIBUTORS “AS IS” AND
// ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
// IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
// ARE DISCLAIMED. IN NO EVENT SHALL THE AUTHOR OR CONTRIBUTORS BE LIABLE
// FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
// DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS
// OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION)
// HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT
// LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY
// OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF
// SUCH DAMAGE.
package main

import "math"

// msun __ldexp_exp, for large positive x and exponent 0 or -1.
func floatMathLdexpExp(x float64, exponent int) float64 {
	y := floatMathExp(float64(x - 1246.97177782734161156))
	bits := math.Float64bits(y)
	exponent += int(bits>>52) - (1023 + 1023) + 1799
	y = math.Float64frombits((bits & 0xfffffffffffff) | (2046 << 52))
	scale := math.Float64frombits(uint64(1023+exponent) << 52)
	return float64(y * scale)
}

func floatMathSinh(x float64) float64 {
	ax := math.Abs(x)
	ix := math.Float64bits(ax) >> 32
	if ix >= 0x7ff00000 {
		return float64(x + x)
	}
	h := 0.5
	if x < 0 {
		h = -0.5
	}
	if ix < 0x40360000 {
		if ix < 0x3e300000 {
			return x
		}
		t := floatMathExpm1(ax)
		if ix < 0x3ff00000 {
			return float64(h * float64(float64(2*t)-float64(float64(t*t)/float64(t+1))))
		}
		return float64(h * float64(t+float64(t/float64(t+1))))
	}
	if ix < 0x40862e42 {
		return float64(h * floatMathExp(ax))
	}
	if ix <= 0x408633ce {
		return float64(float64(h*2) * floatMathLdexpExp(ax, -1))
	}
	return math.Copysign(math.Inf(1), x)
}

func floatMathCosh(x float64) float64 {
	ax := math.Abs(x)
	ix := math.Float64bits(ax) >> 32
	if ix >= 0x7ff00000 {
		return float64(x * x)
	}
	if ix < 0x3fd62e43 {
		t := floatMathExpm1(ax)
		w := float64(1 + t)
		if ix < 0x3c800000 {
			return w
		}
		return float64(1 + float64(float64(t*t)/float64(w+w)))
	}
	if ix < 0x40360000 {
		t := floatMathExp(ax)
		return float64(float64(0.5*t) + float64(0.5/t))
	}
	if ix < 0x40862e42 {
		return float64(0.5 * floatMathExp(ax))
	}
	if ix <= 0x408633ce {
		return floatMathLdexpExp(ax, -1)
	}
	return math.Inf(1)
}

func floatMathTanh(x float64) float64 {
	ax := math.Abs(x)
	ix := math.Float64bits(ax) >> 32
	if ix >= 0x7ff00000 {
		// LM admits only finite Float inputs, including for saturated tanh.
		return math.NaN()
	}
	var z float64
	if ix < 0x40360000 {
		if ix < 0x3e300000 {
			return x
		}
		if ix >= 0x3ff00000 {
			t := floatMathExpm1(float64(2 * ax))
			z = float64(1 - float64(2/float64(t+2)))
		} else {
			t := floatMathExpm1(float64(-2 * ax))
			z = float64(float64(-t) / float64(t+2))
		}
	} else {
		z = 1
	}
	if x < 0 {
		return float64(-z)
	}
	return z
}
