// SplitMix64 and clocks (ADR-051). Python twin: lm/rand_prims.py.
package main

import (
	"crypto/rand"
	"encoding/binary"
	"fmt"
	"os"
	"strconv"
	"strings"
	"time"
)

var randomState uint64
var monoOrigin = time.Now()

// Seed syntax is [+-]?[0-9]+, restricted to Int64, identical to parse_seed.
func parseSeed(s string) (int64, error) {
	sign := ""
	digits := s
	if len(digits) > 0 && (digits[0] == '+' || digits[0] == '-') {
		sign, digits = digits[:1], digits[1:]
	}
	if digits == "" || strings.Trim(digits, "0123456789") != "" {
		return 0, fmt.Errorf("seed must be a signed 64-bit decimal integer")
	}
	digits = strings.TrimLeft(digits, "0")
	if digits == "" {
		digits = "0"
	}
	return strconv.ParseInt(sign+digits, 10, 64)
}

func seedFromEnv() {
	if s, ok := os.LookupEnv("LM_SEED"); ok {
		seed, err := parseSeed(s)
		if err != nil {
			fmt.Fprintln(os.Stderr, "LM_SEED must be a signed 64-bit decimal integer")
			os.Exit(3)
		}
		randomState = uint64(seed)
		return
	}
	var b [8]byte
	if _, err := rand.Read(b[:]); err != nil {
		panic(err)
	}
	randomState = binary.LittleEndian.Uint64(b[:])
}

func randomNext() uint64 {
	randomState += 0x9E3779B97F4A7C15
	z := randomState
	z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9
	z = (z ^ (z >> 27)) * 0x94D049BB133111EB
	return z ^ (z >> 31)
}

func prim_rand_int(lo, hi Value) Value {
	low := uint64(lo.(int64))
	span := uint64(hi.(int64)) - low
	if span == ^uint64(0) {
		return int64(low + randomNext())
	}
	n := span + 1
	// 2^64 % n without representing 2^64; zero means every word is accepted.
	remainder := (-n) % n
	limit := -remainder
	x := randomNext()
	for remainder != 0 && x >= limit {
		x = randomNext()
	}
	return int64(low + x%n)
}

func prim_rand_float() Value   { return float64(randomNext()>>11) * 0x1p-53 }
func prim_time_now_ms() Value  { return time.Now().UnixMilli() }
func prim_time_mono_ms() Value { return time.Since(monoOrigin).Milliseconds() }
