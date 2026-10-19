"""Unit tests for Unicode simple casing, codes, escapes, trim, and args replacement (ADR-063)."""
from __future__ import annotations

import hashlib
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest

from lm.printer import escape_str
from lm.sexpr import read
from lm.str_prims import TRIM_CHARS, from_codes, lower, to_codes, trim, upper
from lm.unicode_tables import to_lower_code, to_lower_str, to_upper_code, to_upper_str
from lm.values import LmFail, show

ROOT = Path(__file__).resolve().parents[2]


class UnicodeCasingTests(unittest.TestCase):
    def test_spot_checks(self):
        # "ß" -> "ß" for both upper and lower
        self.assertEqual(to_upper_str("ß"), "ß")
        self.assertEqual(to_lower_str("ß"), "ß")
        self.assertEqual(len(to_upper_str("ß")), 1)
        self.assertEqual(len(to_lower_str("ß")), 1)

        # "ǅ".upper -> "Ǆ", "ǅ".lower -> "ǆ"
        self.assertEqual(to_upper_str("ǅ"), "Ǆ")
        self.assertEqual(to_lower_str("ǅ"), "ǆ")

        # "İ".lower -> "i" (U+0069)
        self.assertEqual(to_lower_str("İ"), "i")
        self.assertEqual(len(to_lower_str("İ")), 1)

    def test_all_scalars_python_and_go(self):
        # Digest of all 1,112,064 Unicode scalars
        h_up = hashlib.sha256()
        h_lo = hashlib.sha256()
        count = 0
        buf = bytearray(8)
        for cp in range(0x110000):
            if 0xD800 <= cp <= 0xDFFF:
                continue
            count += 1
            u = to_upper_code(cp)
            l = to_lower_code(cp)
            struct.pack_into(">II", buf, 0, cp, u)
            h_up.update(buf)
            struct.pack_into(">II", buf, 0, cp, l)
            h_lo.update(buf)

        self.assertEqual(count, 1112064)
        py_up_digest = h_up.hexdigest()
        py_lo_digest = h_lo.hexdigest()
        self.assertEqual(py_up_digest, "cf3964db6eba1a904d433b63bf3cd861fc9ea429eb3793171ede9c905a861a2e")
        self.assertEqual(py_lo_digest, "95e5d3084e7ddd539abdd47b22faa5574573f33b6a6faee71fd8c139d157c9df")

        # Check Go runtime twin produces identical digests
        go_code = """package main

import (
	"crypto/sha256"
	"encoding/binary"
	"fmt"
)

func main() {
	hUp := sha256.New()
	hLo := sha256.New()
	buf := make([]byte, 8)
	for cp := int32(0); cp <= 0x10ffff; cp++ {
		if cp >= 0xd800 && cp <= 0xdfff {
			continue
		}
		u := toUpperRune(rune(cp))
		l := toLowerRune(rune(cp))
		binary.BigEndian.PutUint32(buf[0:4], uint32(cp))
		binary.BigEndian.PutUint32(buf[4:8], uint32(u))
		hUp.Write(buf)

		binary.BigEndian.PutUint32(buf[4:8], uint32(l))
		hLo.Write(buf)
	}
	fmt.Printf("%x\\n%x\\n", hUp.Sum(nil), hLo.Sum(nil))
}
"""
        with tempfile.TemporaryDirectory() as td:
            runner_go = Path(td) / "runner.go"
            runner_go.write_text(go_code, encoding="utf-8")
            table_go = Path(td) / "unicode_tables.go"
            shutil.copyfile(ROOT / "lm" / "runtime" / "go" / "unicode_tables.go", table_go)
            p = subprocess.run(["go", "run", str(runner_go), str(table_go)], capture_output=True, text=True)
            self.assertEqual(p.returncode, 0, p.stderr)
            lines = p.stdout.strip().splitlines()
            self.assertEqual(lines[0], py_up_digest)
            self.assertEqual(lines[1], py_lo_digest)


class UnicodeCodesTests(unittest.TestCase):
    def test_to_codes(self):
        self.assertEqual(to_codes(None, "ABC"), (65, 66, 67))
        self.assertEqual(to_codes(None, ""), ())
        self.assertEqual(to_codes(None, "héllo"), (104, 233, 108, 108, 111))

    def test_from_codes(self):
        self.assertEqual(from_codes(None, (65, 66, 67)), "ABC")
        self.assertEqual(from_codes(None, ()), "")

        # Errors: negative, > 0x10FFFF, surrogate
        with self.assertRaises(LmFail) as ctx:
            from_codes(None, (65, -1, 67))
        self.assertEqual(ctx.exception.id, "str.BadCode")
        self.assertEqual(ctx.exception.args_, (-1,))

        with self.assertRaises(LmFail) as ctx:
            from_codes(None, (65, 0x110000, 67))
        self.assertEqual(ctx.exception.id, "str.BadCode")
        self.assertEqual(ctx.exception.args_, (0x110000,))

        with self.assertRaises(LmFail) as ctx:
            from_codes(None, (65, 0xD800, 67))
        self.assertEqual(ctx.exception.id, "str.BadCode")
        self.assertEqual(ctx.exception.args_, (0xD800,))

        # Left-to-right order: first invalid value reported
        with self.assertRaises(LmFail) as ctx:
            from_codes(None, (65, -5, 0xD800, 0x110000))
        self.assertEqual(ctx.exception.args_, (-5,))


class EscapeRoundTripTests(unittest.TestCase):
    def test_control_character_round_trip(self):
        # Test with NUL, CR, U+007F, U+0085
        chars = [0, 13, 127, 133]
        s = from_codes(None, chars)

        # Printed representation
        printed = show(s)
        self.assertEqual(printed, r'"\u{0}\u{d}\u{7f}\u{85}"')

        # Reading printed text back recovers the exact string
        node, diags = read(f"({printed})")
        self.assertEqual(diags, [])
        self.assertEqual(node.items[0].value, s)

    def test_escape_str_newlines_and_tabs(self):
        s = "a\nb\tc"
        self.assertEqual(escape_str(s), r'"a\nb\tc"')


class PinnedTrimTests(unittest.TestCase):
    def test_pinned_trim_set(self):
        pinned_cps = (
            *range(0x09, 0x0E), *range(0x1C, 0x21), 0x85, 0xA0, 0x1680,
            *range(0x2000, 0x200B), 0x2028, 0x2029, 0x202F, 0x205F, 0x3000
        )
        self.assertEqual(len(TRIM_CHARS), len(pinned_cps))
        ws = "".join(chr(cp) for cp in pinned_cps)
        s = ws + "hello world" + ws
        self.assertEqual(trim(None, s), "hello world")
        self.assertEqual(trim(None, ws), "")


class IoArgsUtf8ReplacementTests(unittest.TestCase):
    def test_invalid_utf8_in_all_targets(self):
        # Write an entry point that prints the first argument
        src = (
            '(module echo\n'
            '  (purpose "Echo raw args.")\n'
            '  (use io)\n'
            '  (export main)\n'
            '  (fn main\n'
            '    (purpose "Entry.")\n'
            '    (sig -> Int)\n'
            '    (eff io.in io.out)\n'
            '    (body (match (io.args) ((cons arg _) (do (io.print arg) 0)) (_ 1)))))\n'
        )
        raw_invalid_arg = b"foo\xffbar\xe2\x82baz"
        expected_output = "foo\ufffdbar\ufffdbaz\n"

        with tempfile.TemporaryDirectory() as td:
            src_dir = Path(td) / "src"
            src_dir.mkdir()
            lm_file = src_dir / "echo.lm"
            lm_file.write_text(src, encoding="utf-8")

            # 1. Interpreter
            proc = subprocess.run(
                [sys.executable, "-m", "lm", "run", "echo.main", "--allow", "io.in", "--allow", "io.out", "--", raw_invalid_arg],
                cwd=td,
                env={"PYTHONPATH": str(ROOT)},
                capture_output=True,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr.decode("utf-8", errors="replace"))
            self.assertIn(expected_output, proc.stdout.decode("utf-8"))

            # 2. Go binary
            go_bin = Path(td) / "echo_go"
            proc_build = subprocess.run(
                [sys.executable, "-m", "lm", "build", "echo.main", str(lm_file), "-o", str(go_bin)],
                cwd=ROOT,
                capture_output=True,
            )
            self.assertEqual(proc_build.returncode, 0, proc_build.stderr.decode("utf-8", errors="replace"))
            proc_run = subprocess.run([str(go_bin), raw_invalid_arg], capture_output=True)
            self.assertEqual(proc_run.returncode, 0, proc_run.stderr.decode("utf-8", errors="replace"))
            self.assertEqual(proc_run.stdout.decode("utf-8"), expected_output)

            # 3. Python target
            py_bin = Path(td) / "echo.py"
            proc_py_build = subprocess.run(
                [sys.executable, "-m", "lm", "build", "--target", "py", "echo.main", str(lm_file), "-o", str(py_bin)],
                cwd=ROOT,
                capture_output=True,
            )
            self.assertEqual(proc_py_build.returncode, 0, proc_py_build.stderr.decode("utf-8", errors="replace"))
            proc_py_run = subprocess.run([sys.executable, str(py_bin), raw_invalid_arg], capture_output=True)
            self.assertEqual(proc_py_run.returncode, 0, proc_py_run.stderr.decode("utf-8", errors="replace"))
            self.assertEqual(proc_py_run.stdout.decode("utf-8"), expected_output)


if __name__ == "__main__":
    unittest.main()
