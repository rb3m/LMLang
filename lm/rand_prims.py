"""SplitMix64 and clock prims (ADR-051); Go twins in runtime/go/rand.go."""
from __future__ import annotations

import os
import re
import time

MASK = (1 << 64) - 1


def parse_seed(text):
    """A signed ASCII decimal Int64; never accept Python's extra int syntaxes."""
    if not re.fullmatch(r'[+-]?[0-9]+', text):
        raise ValueError('seed must be a signed 64-bit decimal integer')
    # Bound the input before int() (also avoids Python's decimal digit limit).
    digits = text.lstrip('+-').lstrip('0') or '0'
    if len(digits) > 19:
        raise ValueError('seed must be a signed 64-bit decimal integer')
    n = int(('-' if text.startswith('-') else '') + digits)
    if not -(1 << 63) <= n < (1 << 63):
        raise ValueError('seed must be a signed 64-bit decimal integer')
    return n


class SplitMix64:
    def __init__(self, seed=None):
        self.state = (int.from_bytes(os.urandom(8), 'little') if seed is None else seed) & MASK

    def next(self):
        self.state = (self.state + 0x9E3779B97F4A7C15) & MASK
        z = self.state
        z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & MASK
        z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & MASK
        return z ^ (z >> 31)

    def int(self, lo, hi):
        span = (hi - lo) & MASK
        if span == MASK:
            x = self.next()
        else:
            n = span + 1
            limit = (1 << 64) - ((1 << 64) % n)
            x = self.next()
            while x >= limit:
                x = self.next()
            x %= n
        result = (lo + x) & MASK
        return result if result < (1 << 63) else result - (1 << 64)

    def float(self):
        return (self.next() >> 11) * 2.0**-53


RAND_PRIMS = {
    'rand.int': lambda it, lo, hi: it.rng.int(lo, hi),
    'rand.float': lambda it: it.rng.float(),
    'time.now-ms': lambda it: time.time_ns() // 1_000_000,
    'time.mono-ms': lambda it: time.monotonic_ns() // 1_000_000,
}
