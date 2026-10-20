"""E-SERVE selection fixtures cover both server entry commands."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from lm.build import find_go

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests/spec/serve"


class ServeEntryTests(unittest.TestCase):
    def test_missing_effect_is_denied_before_reading_request(self):
        for flags in (("--cgi",), ()):
            with self.subTest(flags=flags):
                proc = subprocess.run(
                    [sys.executable, "-m", "lm", "serve", *flags,
                     "effects.handle", str(FIXTURES / "effects.lm")],
                    cwd=ROOT, capture_output=True, timeout=5)
                self.assertEqual(proc.returncode, 1, proc.stderr)
                self.assertEqual(proc.stdout, b"")
                self.assertEqual(json.loads(proc.stderr)["code"],
                                 "E-EFFECT-DENIED")

    def test_declared_output_effect_is_granted_and_protocol_stays_clean(self):
        source = str(FIXTURES / "effects.lm")
        commands = [[sys.executable, "-m", "lm", "serve", "--cgi",
                     "effects.handle", source, "--allow", "io.out"]]
        with tempfile.TemporaryDirectory(prefix="lm-serve-effects-") as tmp:
            for target in ("py", "go"):
                if target == "go" and find_go() is None:
                    sys.stderr.write("SKIP: Go missing; server effects Go test\n")
                    continue
                output = str(Path(tmp) / ("server.py" if target == "py"
                                          else "server"))
                built = subprocess.run(
                    [sys.executable, "-m", "lm", "build", "--serve",
                     "effects.handle", source, "--target", target,
                     "-o", output], cwd=ROOT, capture_output=True)
                self.assertEqual(built.returncode, 0, built.stderr)
                commands.append([sys.executable, output] if target == "py"
                                else [output])
            request_env = {**os.environ, "REQUEST_METHOD": "GET",
                           "REQUEST_URI": "/", "CONTENT_LENGTH": "0"}
            for command in commands:
                with self.subTest(command=command):
                    proc = subprocess.run(command, cwd=ROOT, env=request_env,
                                          input=b"", capture_output=True)
                    self.assertEqual(proc.returncode, 0, proc.stderr)
                    self.assertEqual(proc.stdout, b"Status: 200 OK\r\n"
                                     b"Content-Length: 2\r\n\r\nok")
                    self.assertEqual(proc.stderr, b"handler-log\n")

    def test_invalid_handler_fixtures(self):
        cases = json.loads((FIXTURES / "entry.expect").read_text())
        with tempfile.TemporaryDirectory(prefix="lm-serve-entry-") as tmp:
            src = Path(tmp) / "src"
            src.mkdir()
            shutil.copyfile(FIXTURES / "entry.lm", src / "entry.lm")
            for name in cases:
                for command in (("serve", "--cgi"), ("serve",),
                                ("build", "--target", "py", "--serve"),
                                ("build", "--target", "go", "--serve")):
                    with self.subTest(name=name, command=command):
                        args = [*command, name]
                        if command[0] == "build":
                            args += ["-o", str(Path(tmp) / "out.py")]
                        proc = subprocess.run(
                            [sys.executable, "-m", "lm", *args], cwd=tmp,
                            env={**os.environ, "PYTHONPATH": str(ROOT)},
                            capture_output=True, text=True)
                        self.assertEqual(proc.returncode, 1, proc.stderr)
                        diags = [json.loads(line) for line in
                                 (proc.stdout + proc.stderr).splitlines()
                                 if line.startswith("{")]
                        self.assertIn("E-SERVE", [d["code"] for d in diags])
                        if command[0] == "serve":
                            self.assertEqual(proc.stdout, "")
