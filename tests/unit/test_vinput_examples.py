"""The virtual joystick log clause uses the fake clock and reports E-EXAMPLE."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

LM = Path(__file__).resolve().parents[2] / "bin/lm"
MODULE = """(module example-probe
  (purpose "Validate virtual joystick example metadata.")
  (use hid vinput)
  (fn main
    (purpose "Advance the HID clock and record joystick operations and cleanup.")
    (sig -> Unit)
    (eff hid.io vinput.emit)
    (fails hid.HidError vinput.VinputError)
    (example () (given) => unit CHECK)
    (body
      (let
        ((first (vinput.create (new vinput.Spec (name "One") (vendor 0) (product 0)
                                 (axes (list)) (buttons 1) (hats 0))))
          (elapsed (hid.wait (list) 5))
          (second (vinput.create (new vinput.Spec (name "Two") (vendor 0) (product 0)
                                  (axes (list)) (buttons 1) (hats 0)))))
        (do (vinput.button second 0 true) (vinput.sync second)))))
  (fn unsupported
    (purpose "Check an unknown capability.")
    (sig -> Bool)
    (eff vinput.emit)
    (example () (given) => false (vinput-log))
    (body (vinput.supports "unknown"))))\n"""


class VinputExamples(unittest.TestCase):
    def run_example(self, clause, command):
        with tempfile.TemporaryDirectory(prefix="lm-vinput-example-") as directory:
            work = Path(directory)
            (work / "lm.deps").write_text("(deps (ext hid) (ext vinput))\n")
            (work / "src").mkdir()
            (work / "src/example-probe.lm").write_text(MODULE.replace("CHECK", clause))
            return subprocess.run([LM, command], cwd=work, capture_output=True,
                                  text=True, timeout=10)

    def test_clock_and_cleanup_order(self):
        result = self.run_example(
            '(vinput-log (create 0 "v1" "One") (create 5 "v2" "Two") '
            '(frame 5 "v2" ((button 0 true))) (close 5 "v1") (close 5 "v2"))', "test")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("2 examples, 0 failed", result.stderr)

    def test_malformed_entries(self):
        for entry in ('frame', '(bogus 0 "v1")', '(create -1 "v1" "One")',
                      '(close 0 "")', '(frame 0 "v2" "events")',
                      '(frame 0 "v2" ((button 0 1)))', '(frame 0 "v2" ((hat 4 0 0)))',
                      '(frame 0 "v2" ((axis "pitch" 10)))'):
            with self.subTest(entry=entry):
                result = self.run_example(f"(vinput-log {entry})", "check")
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertIn("E-EXAMPLE", [json.loads(line)["code"]
                                            for line in (result.stdout + result.stderr).splitlines()
                                            if line.startswith("{")])
