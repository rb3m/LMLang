"""Hardware-free tests for Linux HID and its static Go implementation."""
import errno
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

from lm import build

if sys.platform.startswith("linux"):
    from lm import hid_linux
    from lm.hid_adapter import MAX_QUEUE, HidDev, HidProblem


@unittest.skipUnless(sys.platform.startswith("linux"), "requires Linux")
class LinuxHidTests(unittest.TestCase):
    def test_descriptor(self):
        mouse = bytes.fromhex("05010902a1018501c0")
        self.assertEqual(hid_linux.descriptor_info(mouse), (1, 2, True))
        long_item = bytes.fromhex("fe030085aa0005000900a101c0")
        self.assertEqual(hid_linux.descriptor_info(long_item), (0, 0, False))
        self.assertEqual(hid_linux.descriptor_info(b"\x85"), (-1, -1, False))
        self.assertEqual(hid_linux.descriptor_info(bytes.fromhex("0501a1010902c0")),
                         (1, -1, False))
        self.assertEqual(hid_linux.descriptor_info(bytes.fromhex("0b03000c00a101c0")),
                         (12, 3, False))

    def test_uevent(self):
        self.assertEqual(hid_linux.parse_uevent(
            "HID_ID=0003:0000046D:0000C52B\nHID_NAME=USB=Mouse\nbad\n"),
            (3, 0x046D, 0xC52B, "USB=Mouse", ""))
        self.assertEqual(hid_linux.parse_uevent("HID_ID=invalid\nHID_UNIQ=42\n"),
                         (-1, -1, -1, "", "42"))

    def test_enumeration_and_open(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sys_root = root / "class"
            sys_root.mkdir()
            self.fake_device(root, sys_root, "hidraw0", "0003:046D:C52B.0007")
            self.fake_device(root, sys_root, "hidraw1", "0003:046D:C52B.0002")
            (root / "hidraw0").write_bytes(b"\x01abc")
            adapter = hid_linux.LinuxHid(sys_root, root)
            self.addCleanup(adapter.shutdown)
            rows = adapter.invoke("enumerate")
            self.assertEqual([row[0] for row in rows],
                             ["linux:0003:046d:c52b.0002", "linux:0003:046d:c52b.0007"])
            self.assertEqual(rows[1][1:], (0x046D, 0xC52B, 1, 2, 10, "A mouse", ""))
            handle = adapter.invoke("open", rows[1][0])
            self.assertEqual(adapter.invoke("wait", [handle, handle], 0), (0, 1))
            self.assertEqual(adapter.invoke("read", handle), (1, b"abc"))
            with self.assertRaises(HidProblem) as failure:
                adapter.invoke("read", handle)
            self.assertEqual(failure.exception.args, (handle.id, "disconnected"))

    def fake_device(self, root, sys_root, node, identity):
        device = root / "usb-interface" / identity
        device.mkdir(parents=True)
        (device.parent / "bInterfaceNumber").write_text("0a\n")
        (device / "uevent").write_text("HID_ID=0003:046D:C52B\nHID_NAME=A mouse\n")
        (device / "report_descriptor").write_bytes(bytes.fromhex("05010902a1018501c0"))
        (sys_root / node).mkdir()
        (sys_root / node / "device").symlink_to(device)

    def test_framing_and_ioctl(self):
        self.assertEqual(hid_linux.input_report(True, b"\x03\x03a"), (3, b"\x03a"))
        self.assertEqual(hid_linux.input_report(False, b"\x00a"), (0, b"\x00a"))
        self.assertEqual(hid_linux.frame_report(0, b"a"), b"\x00a")
        self.assertEqual(hid_linux.frame_report(3, b"a"), b"\x03a")
        self.assertEqual(hid_linux.feature_payload(0, b"\x00a", 2), b"\x00a")
        self.assertEqual(hid_linux.feature_payload(3, b"\x03a", 2), b"a")
        self.assertEqual(hid_linux.feature_payload(3, b"\x04a", 2), b"\x04a")
        self.assertEqual(hid_linux.feature_payload(0, b"\0\0a", 2, zero_prefixed=True),
                         b"\0a")
        self.assertEqual(hid_linux.feature_request(6, 91), 0xC05B4806)
        self.assertEqual(hid_linux.feature_request(7, 91), 0xC05B4807)
        self.assertEqual(hid_linux.EVIOCGRAB, 0x40044590)

    def test_errors(self):
        for code, before, after in [
            (errno.EACCES, "permission", "permission"),
            (errno.EPERM, "permission", "permission"),
            (errno.EBUSY, "busy", "busy"),
            (errno.ENOENT, "not-found", "disconnected"),
            (errno.ENODEV, "not-found", "disconnected"),
            (errno.ENXIO, "not-found", "disconnected"),
            (errno.EIO, "io", "io"),
        ]:
            with self.subTest(code=code):
                self.assertEqual(hid_linux.error_category(code), before)
                self.assertEqual(hid_linux.error_category(code, opened=True), after)

    def test_read_only_fallback_rejects_output_and_features(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sys_root = root / "class"
            sys_root.mkdir()
            self.fake_device(root, sys_root, "hidraw0", "0003:046D:C52B.0007")
            adapter = hid_linux.LinuxHid(sys_root, root)
            self.addCleanup(adapter.shutdown)
            ident = adapter.invoke("enumerate")[0][0]
            with patch.object(hid_linux.os, "open",
                              side_effect=[OSError(errno.EACCES, "denied"), -1]) as opened:
                handle = adapter.invoke("open", ident)
            modes = [call.args[1] & os.O_ACCMODE for call in opened.call_args_list]
            self.assertEqual(modes, [os.O_RDWR, os.O_RDONLY])
            for op, args in (("write", (0, b"a")), ("feature-set", (0, b"a")),
                             ("feature-get", (0, 1))):
                with self.subTest(op=op), self.assertRaises(HidProblem) as failure:
                    adapter.invoke(op, handle, *args)
                self.assertEqual(failure.exception.args, (ident, "permission"))

    def test_feature_ioctl_arguments(self):
        adapter = hid_linux.LinuxHid()
        self.addCleanup(adapter.shutdown)
        handle = HidDev("linux:test")
        adapter.open_ids.add(handle.id)
        adapter.devices[handle] = hid_linux._Device(-1, Path("."), False, False,
                                                    zero_prefixed=True)
        calls = []

        def ioctl(fd, request, data):
            calls.append((fd, request, bytes(data)))
            data[:] = b"\x00\x00a"
            return len(data)

        with patch.object(hid_linux.fcntl, "ioctl", side_effect=ioctl):
            adapter.invoke("feature-set", handle, 0, b"bc")
            self.assertEqual(adapter.invoke("feature-get", handle, 0, 2), b"\x00a")
        self.assertEqual(calls, [(-1, 0xC0034806, b"\x00bc"),
                                 (-1, 0xC0034807, b"\x00\x00\x00")])

    def test_grab_rollback(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for event in ("event0", "event1"):
                child = root / "input" / "input0" / event
                child.mkdir(parents=True)
            adapter = hid_linux.LinuxHid(root, root)
            self.addCleanup(adapter.shutdown)
            handle = HidDev("linux:test")
            state = hid_linux._Device(-1, root, False, False)
            adapter.open_ids.add(handle.id)
            adapter.devices[handle] = state
            with patch.object(hid_linux.os, "open", side_effect=[10, 11]) as opened, \
                    patch.object(hid_linux.os, "close") as closed, \
                    patch.object(hid_linux.fcntl, "ioctl",
                                 side_effect=[0, OSError(errno.EBUSY, "busy"), 0]) as ioctl:
                with self.assertRaises(HidProblem) as failure:
                    adapter.invoke("grab", handle, True)
            self.assertEqual(failure.exception.args, (handle.id, "busy"))
            self.assertEqual([call.args[0].name for call in opened.call_args_list],
                             ["event0", "event1"])
            self.assertEqual([call.args[0] for call in closed.call_args_list], [11, 10])
            self.assertEqual([call.args for call in ioctl.call_args_list],
                             [(10, hid_linux.EVIOCGRAB, 1), (11, hid_linux.EVIOCGRAB, 1),
                              (10, hid_linux.EVIOCGRAB, 0)])
            self.assertEqual(state.grabs, [])

    def test_queue_retains_latest_before_disconnect(self):
        adapter = hid_linux.LinuxHid()
        self.addCleanup(adapter.shutdown)
        handle = HidDev("linux:test")
        adapter.open_ids.add(handle.id)
        adapter.devices[handle] = hid_linux._Device(-1, Path("."), True, False)
        reports = [bytes((3, index % 251)) for index in range(MAX_QUEUE + 2)]
        with patch.object(hid_linux.os, "read", side_effect=[
                *reports, OSError(errno.EIO, "removed")]):
            self.assertEqual(adapter.invoke("read", handle), (3, reports[2][1:]))
        self.assertEqual(adapter.invoke("wait", [handle], 0), (0,))
        for report in reports[3:]:
            self.assertEqual(adapter.invoke("read", handle), (3, report[1:]))
        with self.assertRaises(HidProblem) as failure:
            adapter.invoke("read", handle)
        self.assertEqual(failure.exception.args, (handle.id, "disconnected"))

    def test_shutdown_wakes_empty_wait(self):
        adapter = hid_linux.LinuxHid()
        self.addCleanup(adapter.shutdown)
        entered = threading.Event()
        results = []
        poll = adapter._poll

        def entered_poll(*args):
            entered.set()
            return poll(*args)

        with patch.object(adapter, "_poll", side_effect=entered_poll):
            worker = threading.Thread(
                target=lambda: results.append(adapter.invoke("wait", [], 2000)),
                daemon=True)
            worker.start()
            self.assertTrue(entered.wait(1))
            adapter.shutdown()
            worker.join(1)
        self.assertEqual(results, [()])

    def test_go_helpers(self):
        go = build.find_go()
        self.assertIsNotNone(go, "Go toolchain required for Linux HID tests")
        with tempfile.TemporaryDirectory() as temp:
            work = Path(temp)
            build.write_sources("package main\nfunc main() {}\n", work)
            source = Path(__file__).with_name("hid_linux_test.go")
            (work / source.name).write_bytes(source.read_bytes())
            result = subprocess.run(
                [go, "test", "-count=1"], cwd=work, capture_output=True, text=True,
                timeout=180, env={**os.environ, "CGO_ENABLED": "0", "GOOS": "linux",
                                  "GOARCH": "", "GOTOOLCHAIN": "local"},
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
