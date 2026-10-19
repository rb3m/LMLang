import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from lm import build

ROOT = Path(__file__).resolve().parents[2]
WRAPPER = ROOT / "bin" / "lm"


def run(cmd, cwd):
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)


class LmNew(unittest.TestCase):
    def test_scaffold_passes_the_gate(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(run([str(WRAPPER), "new", "greet-app"], d).returncode, 0)
            proj = Path(d) / "greet-app"
            self.assertTrue((proj / "src" / "greet-app.lm").is_file())
            self.assertTrue((proj / "tests" / "accept" / "greet-app.accept").is_file())
            instructions = (proj / "AGENTS.md").read_text()
            self.assertIn("# AGENTS.md: greet-app (an LM project)", instructions)
            self.assertIn("lm guide", instructions)
            self.assertIn("lm slice greet-app.FN", instructions)
            self.assertIn("explicit yes", instructions)
            self.assertIn("lm accept --guard", instructions)
            self.assertLessEqual(len(instructions.splitlines()), 25)
            for filename in ("CLAUDE.md", "GEMINI.md"):
                self.assertEqual((proj / filename).read_text(), "See AGENTS.md.\n")
            self.assertEqual((proj / ".gitignore").read_text(), "/greet-app\n")
            for args in (["fmt", "--check"], ["check"], ["test"], ["accept", "--guard"]):
                p = run([str(WRAPPER), *args], proj)
                self.assertEqual(p.returncode, 0, (args, p.stdout, p.stderr))
            p = run([str(WRAPPER), "run", "greet-app.main", "--allow", "io.in", "--allow", "io.out", "--", "Ana"], proj)
            self.assertEqual(p.stdout, "Hello, Ana!\n0\n")

    def test_refusals(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "busy").mkdir()
            (Path(d) / "busy" / "x").write_text("")
            for args in (["new"], ["new", "Bad_Name"], ["new", "busy"], ["new", "a", "b"]):
                self.assertEqual(run([str(WRAPPER), *args], d).returncode, 3, args)
            self.assertEqual((Path(d) / "busy" / "x").read_text(), "")

    @unittest.skipIf(os.name != "posix" or os.geteuid() == 0, "needs a non-root POSIX user")
    def test_unwritable_parent_is_a_message_not_a_traceback(self):
        with tempfile.TemporaryDirectory() as d:
            locked = Path(d) / "locked"
            locked.mkdir(mode=0o555)
            try:
                p = run([str(WRAPPER), "new", "app"], locked)
            finally:
                locked.chmod(0o755)
            self.assertEqual(p.returncode, 1)
            self.assertIn("lm new: cannot write app", p.stderr)
            self.assertNotIn("Traceback", p.stderr)


class Wrapper(unittest.TestCase):
    def test_works_through_a_symlink_from_any_directory(self):
        with tempfile.TemporaryDirectory() as d:
            link = Path(d) / "bin" / "lm"
            link.parent.mkdir()
            link.symlink_to(WRAPPER)
            env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
            p = subprocess.run([str(link), "run", "math.max", "2", "5"], cwd=d, capture_output=True, text=True, env=env)
            self.assertEqual((p.returncode, p.stdout), (0, "5\n"), p.stderr)

    def test_python_override(self):
        env = dict(os.environ, LM_PYTHON=sys.executable)
        p = subprocess.run([str(WRAPPER), "run", "math.min", "2", "5"], capture_output=True, text=True, env=env)
        self.assertEqual(p.stdout, "2\n", p.stderr)


class FindGo(unittest.TestCase):
    def test_falls_back_to_usual_locations(self):
        with tempfile.TemporaryDirectory() as home:
            fake = Path(home) / ".local" / "go" / "bin" / "go"
            fake.parent.mkdir(parents=True)
            fake.write_text("")
            with mock.patch.dict(os.environ, {"HOME": home, "PATH": "/nonexistent"}), \
                    mock.patch.object(build, "GO_FALLBACKS", ("~/.local/go/bin/go",)):
                os.environ.pop("LM_GO", None)
                self.assertEqual(build.find_go(), str(fake))

    def test_lm_go_pointing_nowhere_means_no_go(self):
        with mock.patch.dict(os.environ, {"LM_GO": "/nonexistent/go"}):
            self.assertIsNone(build.find_go())
