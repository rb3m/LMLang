// LM float math algorithms v1 (ADR-057).
// exp/ln: Go 1.27.2 src/math/{exp,log}.go; never dispatch to arch assembly.
// log2/log10: FreeBSD msun e_log2.c/e_log10.c/k_log.h, Android bionic a0ee078.
// Source: https://android.googlesource.com/platform/bionic/+/a0ee078%5E%21/
// Every arithmetic operation explicitly rounds to binary64 to prohibit FMA.
// Copyright 2009 The Go Authors. All rights reserved.
// Use of this source code is governed by a BSD-style license.
// Redistribution and use in source and binary forms, with or without
// modification, are permitted provided that the following conditions are met:
//   - Redistributions of source code must retain the above copyright notice,
//     this list of conditions and the following disclaimer.
//   - Redistributions in binary form must reproduce the above copyright notice,
//     this list of conditions and the following disclaimer in the documentation
//     and/or other materials provided with the distribution.
//   - Neither the name of Google Inc. nor the names of its contributors may be
//     used to endorse or promote products derived from this software without
//     specific prior written permission.
//
// THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
// AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
// IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
// ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE
// LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
// CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
// SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
// INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
// CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
// ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
// POSSIBILITY OF SUCH DAMAGE.
//
// Original FreeBSD msun e_exp.c and e_log.c notices:
// Copyright (C) 2004 by Sun Microsystems, Inc. All rights reserved.
// Copyright (C) 1993 by Sun Microsystems, Inc. All rights reserved.
// Developed at SunPro, a Sun Microsystems, Inc. business.
// e_log2.c/e_log10.c/k_log.h: Developed at SunSoft, a Sun Microsystems,
// Inc. business. Copyright (C) 1993 by Sun Microsystems, Inc.
// Permission to use, copy, modify, and distribute this software is freely
// granted, provided that this notice is preserved.
package main

import "math"

const (
	lmLn2Hi  = 6.93147180369123816490e-01
	lmLn2Lo  = 1.90821492927058770002e-10
	lmInvLn2 = 0x1.71547652b82fep+0
)

func floatMathExp(x float64) float64 {
	if x > 7.09782712893383973096e+02 {
		return math.Inf(1)
	}
	if x < -7.45133219101941108420e+02 {
		return 0
	}
	if -0x1p-28 < x && x < 0x1p-28 {
		return float64(1 + x)
	}
	var k int
	if x > 0 {
		k = int(float64(float64(lmInvLn2*x) + 0.5))
	} else {
		k = int(float64(float64(lmInvLn2*x) - 0.5))
	}
	hi := float64(x - float64(float64(k)*lmLn2Hi))
	lo := float64(float64(k) * lmLn2Lo)
	return floatMathExpMulti(hi, lo, k)
}

func floatMathExpMulti(hi, lo float64, k int) float64 {
	const (
		p1 = 1.66666666666666657415e-01
		p2 = -2.77777777770155933842e-03
		p3 = 6.61375632143793436117e-05
		p4 = -1.65339022054652515390e-06
		p5 = 4.13813679705723846039e-08
	)
	r := float64(hi - lo)
	t := float64(r * r)
	p := float64(p4 + float64(t*p5))
	p = float64(p3 + float64(t*p))
	p = float64(p2 + float64(t*p))
	p = float64(p1 + float64(t*p))
	c := float64(r - float64(t*p))
	y := float64(1 - float64(float64(lo-float64(float64(r*c)/float64(2-c)))-hi))
	return math.Ldexp(y, k)
}

func floatMathLn(x float64) float64 {
	const (
		l1 = 6.666666666666735130e-01
		l2 = 3.999999999940941908e-01
		l3 = 2.857142874366239149e-01
		l4 = 2.222219843214978396e-01
		l5 = 1.818357216161805012e-01
		l6 = 1.531383769920937332e-01
		l7 = 1.479819860511658591e-01
	)
	f1, ki := math.Frexp(x)
	if f1 < 0x1.6a09e667f3bcdp-1 {
		f1 = float64(f1 * 2)
		ki--
	}
	f := float64(f1 - 1)
	k := float64(ki)
	s := float64(f / float64(2+f))
	s2 := float64(s * s)
	s4 := float64(s2 * s2)
	t1 := float64(l5 + float64(s4*l7))
	t1 = float64(l3 + float64(s4*t1))
	t1 = float64(s2 * float64(l1+float64(s4*t1)))
	t2 := float64(l4 + float64(s4*l6))
	t2 = float64(s4 * float64(l2+float64(s4*t2)))
	r := float64(t1 + t2)
	hfsq := float64(float64(0.5*f) * f)
	return float64(float64(k*lmLn2Hi) - float64(float64(hfsq-float64(float64(s*float64(hfsq+r))+float64(k*lmLn2Lo)))-f))
}

func floatMathLog2(x float64) float64 {
	hi, lo, y := floatMathLogParts(x)
	const invHi = 1.44269504072144627571e+00
	const invLo = 1.67517131648865118353e-10
	valHi := float64(hi * invHi)
	valLo := float64(float64(float64(lo+hi)*invLo) + float64(lo*invHi))
	w := float64(y + valHi)
	valLo = float64(valLo + float64(float64(y-w)+valHi))
	return float64(valLo + w)
}

func floatMathLog10(x float64) float64 {
	hi, lo, y := floatMathLogParts(x)
	const invHi = 4.34294481878168880939e-01
	const invLo = 2.50829467116452752298e-11
	const log2Hi = 3.01029995663611771306e-01
	const log2Lo = 3.69423907715893078616e-13
	valHi := float64(hi * invHi)
	y2 := float64(y * log2Hi)
	valLo := float64(float64(float64(y*log2Lo)+float64(float64(lo+hi)*invLo)) + float64(lo*invHi))
	w := float64(y2 + valHi)
	valLo = float64(valLo + float64(float64(y2-w)+valHi))
	return float64(valLo + w)
}

// msun reduction and k_log1p; Frexp exactly normalizes even subnormals.
// Preserve msun's high-word boundary slightly below sqrt(2), and split the
// reduced logarithm by clearing hi's low 32 bits before compensation.
func floatMathLogParts(x float64) (hi, lo, y float64) {
	frac, k := math.Frexp(x)
	frac = float64(frac * 2)
	k--
	if (math.Float64bits(frac)>>32)&0xfffff >= 0x6a09c {
		frac = float64(frac * 0.5)
		k++
	}
	f := float64(frac - 1)
	const (
		l1 = 6.666666666666735130e-01
		l2 = 3.999999999940941908e-01
		l3 = 2.857142874366239149e-01
		l4 = 2.222219843214978396e-01
		l5 = 1.818357216161805012e-01
		l6 = 1.531383769920937332e-01
		l7 = 1.479819860511658591e-01
	)
	s := float64(f / float64(2+f))
	z := float64(s * s)
	w := float64(z * z)
	t1 := float64(w * float64(l2+float64(w*float64(l4+float64(w*l6)))))
	t2 := float64(l5 + float64(w*l7))
	t2 = float64(l3 + float64(w*t2))
	t2 = float64(z * float64(l1+float64(w*t2)))
	r := float64(t2 + t1)
	hfsq := float64(float64(0.5*f) * f)
	r = float64(s * float64(hfsq+r))
	hi = float64(f - hfsq)
	hi = math.Float64frombits(math.Float64bits(hi) & 0xffffffff00000000)
	lo = float64(float64(float64(f-hi)-hfsq) + r)
	return hi, lo, float64(k)
}

func prim_float_pi() Value { return math.Float64frombits(0x400921fb54442d18) }
func prim_float_e() Value  { return math.Float64frombits(0x4005bf0a8b145769) }

func floatMathPrim(op string, x Value, fn func(float64) float64, positive bool) Value {
	f := x.(float64)
	if positive && f <= 0 {
		numFault("E-FLOAT", op, []Value{f}, -1, false)
	}
	y := fn(f)
	if math.IsInf(y, 0) || math.IsNaN(y) {
		numFault("E-FLOAT", op, []Value{f}, -1, false)
	}
	return normZero(y)
}

func prim_float_exp(x Value) Value   { return floatMathPrim("float.exp", x, floatMathExp, false) }
func prim_float_expm1(x Value) Value { return floatMathPrim("float.expm1", x, floatMathExpm1, false) }
func prim_float_log1p(x Value) Value { return floatMathPrim("float.log1p", x, floatMathLog1p, false) }
func prim_float_ln(x Value) Value    { return floatMathPrim("float.ln", x, floatMathLn, true) }
func prim_float_log2(x Value) Value  { return floatMathPrim("float.log2", x, floatMathLog2, true) }
func prim_float_log10(x Value) Value { return floatMathPrim("float.log10", x, floatMathLog10, true) }

func prim_float_sinh(x Value) Value { return floatMathPrim("float.sinh", x, floatMathSinh, false) }
func prim_float_cosh(x Value) Value { return floatMathPrim("float.cosh", x, floatMathCosh, false) }
func prim_float_tanh(x Value) Value { return floatMathPrim("float.tanh", x, floatMathTanh, false) }
