// LM runtime for the Go backend: Float = finite IEEE-754 binary64 (ADR-039).
//
// Every operation rounds to binary64 (nearest, ties to even) and is checked: a NaN or infinite result
// is the fault E-FLOAT, and -0.0 is normalized to 0.0. Each result is wrapped in an explicit
// float64(..) conversion, which the Go spec requires to round, so the compiler may never fuse
// x*y+z into one FMA (it may on arm64 otherwise). Canonical text is Python's repr(float).
package main

import (
	"math"
	"regexp"
	"strconv"
	"strings"
)

// fbits rebuilds a Float literal from its exact bit pattern (emitted by lm/gobackend.py).
func fbits(u uint64) Value { return math.Float64frombits(u) }

// farith is + - * / on Floats; site < 0 means a prelude operator called back by a prim.
func farith(op string, a, b float64, site int) Value {
	var c float64
	switch op {
	case "+":
		c = float64(a + b)
	case "-":
		c = float64(a - b)
	case "*":
		c = float64(a * b)
	default:
		c = float64(a / b) // a zero divisor gives Inf or NaN: the fault below, never DivZero
	}
	if math.IsInf(c, 0) || math.IsNaN(c) {
		numFault("E-FLOAT", op, []Value{a, b}, site, site < 0)
	}
	return normZero(c)
}

// normZero turns -0.0 into 0.0 (ADR-039 item 4); every other value is returned unchanged.
func normZero(c float64) float64 {
	if c == 0 {
		return 0
	}
	return c
}

// showFloat is Python's repr(float): shortest round-trip digits, positional when the decimal
// exponent is in [-4, 16) (always with a `.`), otherwise d[.ddd]e+XX with at least two exponent
// digits. strconv's 'g' differs (it prints 100 for 100.0), so the rule is applied explicitly.
func showFloat(x float64) string {
	if x == 0 {
		return "0.0"
	}
	s := strconv.FormatFloat(x, 'e', -1, 64) // [-]d[.ddd]e±XX, the same digits Python chooses
	mant, exp, _ := strings.Cut(s, "e")
	e, _ := strconv.Atoi(exp)
	if e < -4 || e >= 16 {
		return s
	}
	sign := ""
	if mant[0] == '-' {
		sign, mant = "-", mant[1:]
	}
	digits := strings.Replace(mant, ".", "", 1)
	if e < 0 {
		return sign + "0." + strings.Repeat("0", -e-1) + digits
	}
	if len(digits) <= e+1 {
		return sign + digits + strings.Repeat("0", e+1-len(digits)) + ".0"
	}
	return sign + digits[:e+1] + "." + digits[e+1:]
}

// ---- prims: module float ------------------------------------------------------------------------

func prim_float_from_int(n Value) Value { return normZero(float64(n.(int64))) }

func prim_float_sqrt(x Value) Value {
	f := x.(float64)
	if f < 0 {
		numFault("E-FLOAT", "float.sqrt", []Value{f}, -1, false)
	}
	return float64(math.Sqrt(f))
}

// toInt checks the already-rounded integer t against Int bounds. 2^63 is exact in binary64, so the
// comparison is exact; never compare against float64(MaxInt64), which rounds up to 2^63.
func toInt(op string, x, t float64) Value {
	if t < -9223372036854775808.0 || t >= 9223372036854775808.0 {
		numFault("E-OVERFLOW", op, []Value{x}, -1, false)
	}
	return int64(t)
}

func prim_float_floor(x Value) Value { return toInt("float.floor", x.(float64), math.Floor(x.(float64))) }

func prim_float_ceil(x Value) Value { return toInt("float.ceil", x.(float64), math.Ceil(x.(float64))) }

// math.Round rounds half away from zero, exactly (no x+0.5 rounding error).
func prim_float_round(x Value) Value { return toInt("float.round", x.(float64), math.Round(x.(float64))) }

func prim_float_trunc(x Value) Value { return toInt("float.trunc", x.(float64), math.Trunc(x.(float64))) }

// ---- prims: str.from-float / str.to-float --------------------------------------------------------

func prim_str_from_float(x Value) Value { return showFloat(x.(float64)) }

// decimalText is the text str.to-float accepts (no whitespace, `_`, hex, inf or nan); twin of
// lm/float_prims.py DECIMAL_RE.
var decimalText = regexp.MustCompile(`^[+-]?([0-9]+(\.[0-9]*)?|\.[0-9]+)([eE][+-]?[0-9]+)?$`)

func prim_str_to_float(s Value) Value {
	t := s.(string)
	if !decimalText.MatchString(t) {
		return V_None
	}
	f, err := strconv.ParseFloat(t, 64)
	if math.IsInf(f, 0) || math.IsNaN(f) || (err != nil && f != 0) {
		return V_None
	}
	return mkSome(normZero(f))
}
