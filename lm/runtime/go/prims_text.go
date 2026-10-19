// String prims added in M10 (ADR-045); conventions as in prims.go. Indices count code points,
// like the Python twins in lm/str_prims.py.
package main

import (
	"strings"
	"unicode/utf8"
)

func prim_str_index_of(s, part Value) Value {
	t := s.(string)
	i := strings.Index(t, part.(string))
	if i < 0 {
		return V_None
	}
	return mkSome(int64(utf8.RuneCountInString(t[:i])))
}

func prim_str_repeat(s, n Value) Value {
	if n.(int64) <= 0 {
		return ""
	}
	return strings.Repeat(s.(string), int(n.(int64)))
}

// prim_str_replace leaves s unchanged for an empty `old` (Go and Python would insert between characters).
func prim_str_replace(s, old, replacement Value) Value {
	if old.(string) == "" {
		return s
	}
	return strings.ReplaceAll(s.(string), old.(string), replacement.(string))
}

// mapASCII shifts only the bytes in [lo, hi] by delta; other bytes (all of multi-byte UTF-8) stay.
func mapASCII(s string, lo, hi byte, delta int) string {
	b := []byte(s)
	for i, c := range b {
		if c >= lo && c <= hi {
			b[i] = byte(int(c) + delta)
		}
	}
	return string(b)
}

func prim_str_upper_ascii(s Value) Value { return mapASCII(s.(string), 'a', 'z', 'A'-'a') }

func prim_str_lower_ascii(s Value) Value { return mapASCII(s.(string), 'A', 'Z', 'a'-'A') }

func prim_str_upper(s Value) Value { return toUpperString(s.(string)) }

func prim_str_lower(s Value) Value { return toLowerString(s.(string)) }

func prim_str_to_codes(s Value) Value {
	runes := []rune(s.(string))
	out := make([]Value, len(runes))
	for i, r := range runes {
		out[i] = int64(r)
	}
	return out
}

func prim_str_from_codes(cs Value) Value {
	items := cs.([]Value)
	for _, v := range items {
		c := v.(int64)
		if c < 0 || c > 0x10ffff || (c >= 0xd800 && c <= 0xdfff) {
			lmFail("str.BadCode", c)
		}
	}
	runes := make([]rune, len(items))
	for i, v := range items {
		runes[i] = rune(v.(int64))
	}
	return string(runes)
}
