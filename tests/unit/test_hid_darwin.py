"""Hardware-free tests for the macOS HID adapter and Go build selection."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from lm import build, hid_darwin


class DarwinHidTests(unittest.TestCase):
    def test_report_framing(self):
        self.assertEqual(hid_darwin.frame_report(0, b"\x00a"), b"\x00a")
        self.assertEqual(hid_darwin.frame_report(3, b"\x03a"), b"\x03\x03a")
        self.assertEqual(hid_darwin.input_payload(0, b"\x00a"), b"\x00a")
        self.assertEqual(hid_darwin.input_payload(3, b"\x03\x03a"), b"\x03a")
        self.assertEqual(hid_darwin.input_payload(3, b"\x03"), b"")
        self.assertEqual(hid_darwin.feature_payload(3, b"\x03a"), b"a")
        self.assertEqual(hid_darwin.feature_payload(3, b"\x04a"), b"\x04a")
        self.assertEqual(hid_darwin.feature_payload(0, b"\x00a"), b"\x00a")

    def test_device_id(self):
        self.assertEqual(hid_darwin.device_id(0xFEDCBA9876543210),
                         "darwin:fedcba9876543210")

    def test_error_mapping(self):
        self.assertEqual(hid_darwin.error_category(-536870174), "permission")
        self.assertEqual(hid_darwin.error_category(0xE00002C5), "busy")
        self.assertEqual(hid_darwin.error_category(0xE00002D9), "io")
        self.assertEqual(hid_darwin.error_category(0xE00002D9, opened=True),
                         "disconnected")
        self.assertEqual(hid_darwin.error_category(0xE00002BC), "io")

    @unittest.skipUnless(sys.platform == "darwin", "requires the macOS SDK")
    def test_go_helpers(self):
        go = build.find_go()
        if go is None:
            self.skipTest("Go toolchain unavailable")
        with tempfile.TemporaryDirectory() as temp:
            work = Path(temp)
            build.write_sources("package main\nfunc main() {}\n", work)
            source = Path(__file__).with_name("hid_darwin_test.go")
            (work / source.name).write_bytes(source.read_bytes())
            result = subprocess.run(
                [go, "test"], cwd=work, capture_output=True, text=True, timeout=180,
                env={**os.environ, "CGO_ENABLED": "1", "GOOS": "darwin",
                     "GOARCH": "", "GOTOOLCHAIN": "local"},
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


class HidBuildTests(unittest.TestCase):
    @patch.dict(os.environ, {"GOOS": "", "CGO_ENABLED": "1"})
    def test_go_build_cgo_flag(self):
        cases = (("darwin", None, True, "1"), ("darwin", "darwin", True, "1"),
                 ("darwin", "linux", True, "0"), ("darwin", None, False, "0"),
                 ("linux", None, True, "0"), ("linux", "darwin", False, "0"))
        for host, target, hid, expected in cases:
            with self.subTest(host=host, target=target, hid=hid):
                self.check_cgo(host, target, hid, expected)

    @patch.dict(os.environ, {"GOOS": "darwin"})
    def test_go_build_cgo_inherited_target(self):
        self.check_cgo("darwin", None, True, "1")
        self.check_cgo("darwin", "linux", True, "0")

    def test_go_build_cross_darwin_hid(self):
        with patch("lm.build.sys.platform", "linux"):
            with self.assertRaisesRegex(build.BuildError, "must be built on macOS") as error:
                build._go_env("darwin", hid=True)
            self.assertEqual(error.exception.code, 3)

    def check_cgo(self, host, target, hid, expected):
        with patch("lm.build.sys.platform", host):
            self.assertEqual(build._go_env(target, hid=hid)["CGO_ENABLED"], expected)
