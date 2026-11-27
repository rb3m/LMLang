"""Opt-in uinput/evdev round trip through each LM runtime on Linux."""
import os
from pathlib import Path
import select
import subprocess
import sys
import tempfile
import time
import unittest
import uuid

from lm.vinput_linux import INPUT_EVENT

ROOT = Path(__file__).resolve().parents[2]
LM = ROOT / "bin/lm"
PROBE = """(module live-probe
  (purpose "Hold a joystick open for an evdev round-trip test.")
  (use io vinput)
  (export main)
  (fn main
    (purpose "Send two frames after an evdev reader has attached.")
    (sig -> Unit)
    (eff io.in vinput.emit)
    (fails io.IoError vinput.VinputError)
    (body
      (match
        (io.args)
        ((list name)
          (let
            ((d
                (vinput.create
                  (new vinput.Spec
                    (name name)
                    (vendor 1)
                    (product 1)
                    (axes (list (new vinput.Axis (name "x") (min -10) (max 10))))
                    (buttons 1)
                    (hats 1))))
              (start (io.read-line)))
            (do
              (vinput.axis d "x" 7)
              (vinput.button d 0 true)
              (vinput.hat d 0 -1 1)
              (vinput.sync d)
              (vinput.button d 0 false)
              (vinput.sync d)
              (let ((finish (io.read-line))) (vinput.close d)))))
        (_ unit)))))\n"""
EXPECTED = [(3, 0, 7), (1, 0x120, 1), (3, 0x10, -1), (3, 0x11, 1), (0, 0, 0),
            (1, 0x120, 0), (0, 0, 0)]


@unittest.skipUnless(sys.platform.startswith("linux") and os.environ.get("LM_VINPUT_LIVE") == "1",
                     "set LM_VINPUT_LIVE=1 on a Linux host with writable /dev/uinput")
class VinputLive(unittest.TestCase):
    def event_node(self, name, program):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and program.poll() is None:
            for entry in Path("/sys/class/input").glob("event*"):
                try:
                    actual = (entry / "device/name").read_text().rstrip("\n")
                    if actual == name:
                        return os.open(Path("/dev/input") / entry.name, os.O_RDONLY | os.O_NONBLOCK)
                except (FileNotFoundError, PermissionError):
                    continue  # udev may not have applied the node's ACL yet
            time.sleep(0.02)
        self.fail(f"evdev device {name!r} did not appear")

    def read_events(self, fd):
        events = []
        deadline = time.monotonic() + 5
        while len(events) < len(EXPECTED):
            remaining = max(0, deadline - time.monotonic())
            if not select.select([fd], [], [], remaining)[0]:
                break
            for _, _, kind, code, value in INPUT_EVENT.iter_unpack(os.read(fd, 4096)):
                events.append((kind, code, value))
        return events

    def round_trip(self, command, work, env):
        name = "LM uinput test " + uuid.uuid4().hex
        with subprocess.Popen([*command, name], cwd=work, env=env, stdin=subprocess.PIPE,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE) as program:
            try:
                fd = self.event_node(name, program)
                try:
                    program.stdin.write(b"emit\n")
                    program.stdin.flush()
                    self.assertEqual(self.read_events(fd), EXPECTED)
                finally:
                    os.close(fd)
                _, stderr = program.communicate(input=b"close\n", timeout=5)
                self.assertEqual(program.returncode, 0, stderr.decode())
            finally:
                if program.poll() is None:
                    program.kill()
                program.wait()

    def test_evdev_round_trip(self):
        self.assertTrue(os.access("/dev/uinput", os.W_OK), "/dev/uinput is missing or not writable")
        env = {k: v for k, v in os.environ.items() if k not in ("LM_HID_REPLAY", "LM_HID_REPLAY_LOG")}
        with tempfile.TemporaryDirectory(prefix="lm-vinput-live-") as directory:
            work = Path(directory)
            (work / "lm.deps").write_text("(deps (ext vinput))\n")
            (work / "src").mkdir()
            (work / "src/live-probe.lm").write_text(PROBE)
            self.round_trip([LM, "run", "live-probe.main", "--allow", "vinput.emit",
                             "--allow", "io.in", "--"], work, env)
            for target in ("py", "go"):
                with self.subTest(target=target):
                    exe = work / ("probe-" + target)
                    build = subprocess.run([LM, "build", "live-probe.main", "--target", target, "-o", exe],
                                           cwd=work, env=env, capture_output=True, text=True, timeout=180)
                    self.assertEqual(build.returncode, 0, build.stdout + build.stderr)
                    self.round_trip([exe], work, env)
