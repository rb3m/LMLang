"""Run each HID trace against the interpreter and both build targets."""
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest


ROOT = Path(__file__).resolve().parents[2]
VECTORS = ROOT / "tests/conformance/hid"
PROBE = VECTORS / "probe.lm"
LM = ROOT / "bin/lm"
EFFECTS = ("hid.grab", "hid.io", "io.in", "io.out", "time.now")


class HidConformance(unittest.TestCase):
    def run_vectors(self, target):
        with tempfile.TemporaryDirectory(prefix="lm-hid-") as directory:
            work = Path(directory)
            cache = work / "src"
            cache.mkdir()
            shutil.copyfile(PROBE, cache / PROBE.name)
            (work / "lm.deps").write_text("(deps\n  (ext hid))\n", encoding="utf-8")
            env = dict(os.environ)
            for name in ("LM_HID_REPLAY", "LM_HID_REPLAY_LOG"):
                env.pop(name, None)
            command = self.probe_command(target, work, env)
            for path in sorted(VECTORS.glob("*.json")):
                self.run_vector(command, path, work, env, target)

    def run_vector(self, command, path, work, env, target):
        vector = json.loads(path.read_text(encoding="utf-8"))
        signals = (signal.SIGTERM, signal.SIGINT) if vector.get("interrupt") else (None,)
        for signum in signals:
            with self.subTest(target=target, vector=path.stem, signal=signum):
                self.assert_vector(command, vector, work, env, target, signum)

    def probe_command(self, target, work, env):
        if target == "interpreter":
            allow = [part for effect in EFFECTS for part in ("--allow", effect)]
            return [LM, "run", "probe.main", *allow, "--"]
        executable = work / ("probe.py" if target == "py" else "probe")
        build = subprocess.run(
            [LM, "build", "probe.main", "--target", target, "-o", executable],
            cwd=work, env=env, capture_output=True, text=True, timeout=180,
        )
        self.assertEqual(build.returncode, 0, build.stdout + build.stderr)
        return [executable]

    def assert_vector(self, command, vector, work, env, target, signum):
        trace = work / "trace.json"
        log = work / "replay.jsonl"
        log.unlink(missing_ok=True)
        trace.write_text(json.dumps(vector["trace"]), encoding="utf-8")
        run_env = dict(env, LM_HID_REPLAY_LOG=str(log))
        if not vector.get("os_adapter"):
            run_env["LM_HID_REPLAY"] = str(trace)
        args = [*command, vector["probe"]]
        expected_status = vector.get("returncode", 0)
        if signum is not None:
            run = self.interrupt(args, work, run_env, log, signum)
            expected_status = 128 + signum
            self.assertEqual(run.stderr, "")
        if signum is None:
            run = subprocess.run(
                args, cwd=work, env=run_env, capture_output=True, text=True, timeout=10,
            )
        self.assertEqual(run.returncode, expected_status, run.stderr)
        pattern = vector.get("darwin_stdout_pattern") if sys.platform == "darwin" else None
        suffix = "unit\n" if target == "interpreter" and run.returncode == 0 else ""
        if pattern is None:
            self.assertEqual(run.stdout, vector["stdout"] + suffix, run.stderr)
        if pattern is not None:
            self.assertRegex(run.stdout, r"\A" + pattern + re.escape(suffix) + r"\Z", run.stderr)
        if "fault" in vector:
            self.assertEqual(json.loads(run.stderr)["code"], vector["fault"])
        actual = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
        self.assert_log(actual, vector)

    def interrupt(self, args, work, env, log, signum):
        with subprocess.Popen(
            args, cwd=work, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True,
        ) as program:
            try:
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline and program.poll() is None:
                    if log.exists() and log.read_text().endswith("\n"):
                        program.send_signal(signum)
                        break
                    time.sleep(0.01)
                stdout, stderr = program.communicate(timeout=6)
            finally:
                if program.poll() is None:
                    program.kill()
                    program.communicate()
        return subprocess.CompletedProcess(args, program.returncode, stdout, stderr)

    def assert_log(self, actual, vector):
        self.assertEqual(len(actual), len(vector["log"]), actual)
        tolerance = vector.get("wait_tolerance_ms", 0)
        for item, expected in zip(actual, vector["log"]):
            self.assertEqual({k: v for k, v in item.items() if k != "at-ms"},
                             {k: v for k, v in expected.items() if k != "at-ms"})
            self.assertIs(type(item["at-ms"]), int)
            self.assertGreaterEqual(item["at-ms"], 0)
            self.assertLessEqual(abs(item["at-ms"] - expected["at-ms"]), tolerance, item)
        self.assertEqual([row["at-ms"] for row in actual],
                         sorted(row["at-ms"] for row in actual))
        if "pulse_ms" in vector:
            down, up = [row["at-ms"] for row in actual if row["op"] == "write"]
            low, high = vector["pulse_ms"]
            self.assertGreaterEqual(up - down, low)
            self.assertLessEqual(up - down, high)

    def test_interpreter(self):
        self.run_vectors("interpreter")

    def test_python(self):
        self.run_vectors("py")

    @unittest.skipUnless(shutil.which("go"), "Go toolchain unavailable")
    def test_go(self):
        self.run_vectors("go")
