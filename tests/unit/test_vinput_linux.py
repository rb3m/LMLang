"""Linux uinput ABI, lifecycle and kernel error behavior without a device node."""
import errno
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from lm import build, vinput_linux as linux
from lm.vinput_adapter import AXIS_CODES, VinputAdapter, VinputProblem
from lm.values import Rec


def spec_record(**overrides):
    fields = {
        "name": "Joy", "vendor": 0x1234, "product": 0xFEDC, "buttons": 17, "hats": 1,
        "axes": (Rec("vinput.Axis", (("name", "rz"), ("min", -2), ("max", 1))),),
    }
    return Rec("vinput.Spec", tuple((fields | overrides).items()))


@unittest.skipUnless(sys.platform.startswith("linux"), "Linux uinput ABI")
class LinuxVinputTests(unittest.TestCase):
    def test_abi(self):
        self.assertEqual(
            (linux.UI_DEV_CREATE, linux.UI_DEV_DESTROY, linux.UI_DEV_SETUP,
             linux.UI_ABS_SETUP, linux.UI_SET_EVBIT, linux.UI_SET_KEYBIT, linux.UI_SET_ABSBIT),
            (0x5501, 0x5502, 0x405C5503, 0x401C5504, 0x40045564, 0x40045565, 0x40045567),
        )
        self.assertEqual(dict(AXIS_CODES), dict(zip(
            ("x", "y", "z", "rx", "ry", "rz", "throttle", "rudder", "wheel", "gas", "brake"),
            range(11))))
        self.assertEqual([linux.button_code(i) for i in (0, 15, 16, 55)],
                         [0x120, 0x12F, 0x2C0, 0x2E7])

    @unittest.skipUnless(platform.machine() in ("x86_64", "aarch64"), "64-bit Linux ABI")
    def test_struct_bytes(self):
        self.assertEqual(linux.pack_device(dict(spec_record().items)),
                         bytes.fromhex("06003412dcfe01004a6f79") + bytes(81))
        self.assertEqual(linux.pack_abs(5, -1, -2, 1),
                         bytes.fromhex("05000000fffffffffeffffff01000000") + bytes(12))
        self.assertEqual(linux.pack_event(3, 5, -2),
                         bytes(16) + bytes.fromhex("03000500feffffff"))

    def test_configure_and_change_only_frames(self):
        ioctl = Mock()
        adapter = VinputAdapter(linux.LinuxVinput(ioctl))
        with patch.object(linux.os, "open", return_value=97) as opened, \
                patch.object(linux.os, "write", side_effect=lambda fd, buf: len(buf)) as writer, \
                patch.object(linux.os, "close") as closed:
            dev = adapter.invoke("create", spec_record())
            opened.assert_called_once_with("/dev/uinput",
                                           os.O_WRONLY | os.O_NONBLOCK | os.O_CLOEXEC)
            writer.assert_not_called()
            expected = [(97, linux.UI_SET_EVBIT, i) for i in (1, 3, 0)]
            expected.extend((97, linux.UI_SET_KEYBIT, linux.button_code(i)) for i in range(17))
            expected.append((97, linux.UI_DEV_SETUP, linux.pack_device(dict(spec_record().items))))
            for code, value, low, high in ((5, -1, -2, 1), (16, 0, -1, 1), (17, 0, -1, 1)):
                expected.extend(((97, linux.UI_SET_ABSBIT, code),
                                 (97, linux.UI_ABS_SETUP, linux.pack_abs(code, value, low, high))))
            expected.append((97, linux.UI_DEV_CREATE))
            self.assertEqual([call.args for call in ioctl.call_args_list], expected)

            adapter.invoke("axis", dev, "rz", -1)
            adapter.invoke("sync", dev)
            adapter.invoke("hat", dev, 0, 0, -1)
            adapter.invoke("button", dev, 16, True)
            adapter.invoke("axis", dev, "rz", 1)
            adapter.invoke("sync", dev)
            adapter.invoke("sync", dev)
            end = linux.pack_event(0, 0, 0)
            self.assertEqual([call.args for call in writer.call_args_list], [
                (97, end),
                (97, linux.pack_event(3, 5, 1) + linux.pack_event(1, 0x2C0, 1)
                 + linux.pack_event(3, 17, -1) + end),
                (97, end),
            ])
            adapter.invoke("close", dev)
            adapter.invoke("close", dev)
            adapter.shutdown()
            ioctl.assert_called_with(97, linux.UI_DEV_DESTROY)
            closed.assert_called_once_with(97)

    def test_no_controls_only_enables_sync(self):
        ioctl = Mock()
        adapter = VinputAdapter(linux.LinuxVinput(ioctl))
        with patch.object(linux.os, "open", return_value=97), patch.object(linux.os, "close"):
            adapter.invoke("create", spec_record(axes=(), buttons=0, hats=0))
            adapter.shutdown()
        calls = [call.args for call in ioctl.call_args_list]
        self.assertEqual([call for call in calls if call[1] == linux.UI_SET_EVBIT],
                         [(97, linux.UI_SET_EVBIT, 0)])

    def test_errors_and_retry(self):
        for number, category in ((errno.EPERM, "permission"), (errno.EACCES, "permission"),
                                 (errno.ENOENT, "unsupported"), (errno.ENODEV, "unsupported"),
                                 (errno.EBUSY, "busy"), (errno.ENOTTY, "io")):
            self.assertEqual(linux.error_category(OSError(number, "")), category)
        ioctl = Mock(side_effect=OSError(errno.EBUSY, "busy"))
        adapter = VinputAdapter(linux.LinuxVinput(ioctl))
        with patch.object(linux.os, "open", return_value=97), \
                patch.object(linux.os, "close") as closed, \
                patch.object(linux.os, "write", return_value=0) as writer:
            with self.assertRaises(VinputProblem) as create:
                adapter.invoke("create", spec_record())
            self.assertEqual((create.exception.device, create.exception.category), ("", "busy"))
            closed.assert_called_once_with(97)
            ioctl.side_effect = None
            dev = adapter.invoke("create", spec_record())
            adapter.invoke("button", dev, 0, True)
            with self.assertRaises(VinputProblem) as sync:
                adapter.invoke("sync", dev)
            self.assertEqual((sync.exception.device, sync.exception.category), ("v1", "io"))
            first = writer.call_args
            writer.side_effect = lambda fd, buf: len(buf)
            adapter.invoke("sync", dev)
            self.assertEqual(writer.call_args, first)
            ioctl.side_effect = OSError(errno.ENODEV, "missing")
            with self.assertRaises(VinputProblem):
                adapter.invoke("close", dev)
            self.assertEqual(closed.call_count, 2)
            adapter.shutdown()
            self.assertEqual(closed.call_count, 2)

    def test_go_helpers(self):
        go = build.find_go()
        self.assertIsNotNone(go, "Go toolchain required for Linux uinput tests")
        with tempfile.TemporaryDirectory() as temp:
            work = Path(temp)
            build.write_sources("package main\nfunc main() {}\n", work)
            source = Path(__file__).with_name("vinput_linux_test.go")
            (work / source.name).write_bytes(source.read_bytes())
            result = subprocess.run(
                [go, "test", "-count=1", "-run", "Vinput", "-v"], cwd=work,
                capture_output=True, text=True, timeout=180,
                env={**os.environ, "CGO_ENABLED": "0", "GOOS": "linux",
                     "GOARCH": "", "GOTOOLCHAIN": "local"},
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("--- PASS: TestVinputAdapter", result.stdout)
