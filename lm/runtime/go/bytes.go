package main

import (
	"encoding/hex"
	"strings"
	"unicode/utf8"
)

// Bytes uses immutable string storage with a value type distinct from LM Str.
type Bytes string

func bytesHex(data Bytes) string { return hex.EncodeToString([]byte(data)) }

func prim_bytes_empty() Value            { return Bytes("") }
func prim_bytes_size(b Value) Value      { return int64(len(b.(Bytes))) }
func prim_bytes_at(b, i Value) Value     { return prim_bytes_u8(b, i) }
func prim_bytes_concat(a, b Value) Value { return a.(Bytes) + b.(Bytes) }
func prim_bytes_hex(b Value) Value       { return bytesHex(b.(Bytes)) }
func prim_bytes_from_str(s Value) Value  { return Bytes(s.(string)) }

func prim_bytes_slice(b, start, count Value) Value {
	data := b.(Bytes)
	i := clampCount(start, len(data))
	n := clampCount(count, len(data)-i)
	return data[i : i+n]
}

func isByte(value int64) bool { return 0 <= value && value <= 255 }

func prim_bytes_fill(n, v Value) Value {
	value := v.(int64)
	if !isByte(value) {
		return V_None
	}
	return mkSome(Bytes(strings.Repeat(string([]byte{byte(value)}), int(max(0, n.(int64))))))
}

func prim_bytes_from_list(xs Value) Value {
	items := xs.([]Value)
	data := make([]byte, len(items))
	for i, item := range items {
		value := item.(int64)
		if !isByte(value) {
			return V_None
		}
		data[i] = byte(value)
	}
	return mkSome(Bytes(data))
}

func prim_bytes_to_list(b Value) Value {
	data := b.(Bytes)
	items := make([]Value, len(data))
	for i := range items {
		items[i] = int64(data[i])
	}
	return items
}

func prim_bytes_from_hex(s Value) Value {
	data, err := hex.DecodeString(s.(string))
	if err != nil {
		return V_None
	}
	return mkSome(Bytes(data))
}

func prim_bytes_to_str(b Value) Value {
	text := string(b.(Bytes))
	if !utf8.ValidString(text) {
		return V_None
	}
	return mkSome(text)
}

func fieldFits(data Bytes, offset, width int64) bool {
	return 0 <= offset && offset <= int64(len(data))-width
}

func fieldShift(width, index int64, little bool) int64 {
	if little {
		return 8 * index
	}
	return 8 * (width - 1 - index)
}

func getBytesField(b, i Value, width int64, little, signed bool) Value {
	data, offset := b.(Bytes), i.(int64)
	if !fieldFits(data, offset, width) {
		return V_None
	}
	var value int64
	for k := int64(0); k < width; k++ {
		value |= int64(data[offset+k]) << fieldShift(width, k, little)
	}
	sign := int64(1) << (8*width - 1)
	if signed && value >= sign {
		value -= 2 * sign
	}
	return mkSome(value)
}

func fieldRange(width int64, signed bool) (int64, int64) {
	if signed {
		limit := int64(1) << (8*width - 1)
		return -limit, limit
	}
	return 0, int64(1) << (8 * width)
}

func putBytesField(b, i, v Value, width int64, little, signed bool) Value {
	data, offset, value := b.(Bytes), i.(int64), v.(int64)
	minimum, limit := fieldRange(width, signed)
	if !fieldFits(data, offset, width) || value < minimum || limit <= value {
		return V_None
	}
	out := []byte(data)
	for k := int64(0); k < width; k++ {
		out[offset+k] = byte(value >> fieldShift(width, k, little))
	}
	return mkSome(Bytes(out))
}

func prim_bytes_u8(b, i Value) Value {
	return getBytesField(b, i, 1, false, false)
}

func prim_bytes_put_u8(b, i, v Value) Value {
	return putBytesField(b, i, v, 1, false, false)
}

func prim_bytes_s8(b, i Value) Value {
	return getBytesField(b, i, 1, false, true)
}

func prim_bytes_put_s8(b, i, v Value) Value {
	return putBytesField(b, i, v, 1, false, true)
}

func prim_bytes_u16le(b, i Value) Value {
	return getBytesField(b, i, 2, true, false)
}

func prim_bytes_put_u16le(b, i, v Value) Value {
	return putBytesField(b, i, v, 2, true, false)
}

func prim_bytes_s16le(b, i Value) Value {
	return getBytesField(b, i, 2, true, true)
}

func prim_bytes_put_s16le(b, i, v Value) Value {
	return putBytesField(b, i, v, 2, true, true)
}

func prim_bytes_u16be(b, i Value) Value {
	return getBytesField(b, i, 2, false, false)
}

func prim_bytes_put_u16be(b, i, v Value) Value {
	return putBytesField(b, i, v, 2, false, false)
}

func prim_bytes_s16be(b, i Value) Value {
	return getBytesField(b, i, 2, false, true)
}

func prim_bytes_put_s16be(b, i, v Value) Value {
	return putBytesField(b, i, v, 2, false, true)
}

func prim_bytes_u32le(b, i Value) Value {
	return getBytesField(b, i, 4, true, false)
}

func prim_bytes_put_u32le(b, i, v Value) Value {
	return putBytesField(b, i, v, 4, true, false)
}

func prim_bytes_s32le(b, i Value) Value {
	return getBytesField(b, i, 4, true, true)
}

func prim_bytes_put_s32le(b, i, v Value) Value {
	return putBytesField(b, i, v, 4, true, true)
}

func prim_bytes_u32be(b, i Value) Value {
	return getBytesField(b, i, 4, false, false)
}

func prim_bytes_put_u32be(b, i, v Value) Value {
	return putBytesField(b, i, v, 4, false, false)
}

func prim_bytes_s32be(b, i Value) Value {
	return getBytesField(b, i, 4, false, true)
}

func prim_bytes_put_s32be(b, i, v Value) Value {
	return putBytesField(b, i, v, 4, false, true)
}
