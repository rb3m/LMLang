import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class InstallTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        for agent in (".claude", ".codex", ".gemini"):
            (self.home / agent).mkdir()
        self.bin = self.home / ".local" / "bin"
        self.links = {
            self.bin / "lm": ROOT / "bin" / "lm",
            self.home / ".claude" / "skills" / "lm": ROOT / "skills" / "lm",
            self.home / ".agents" / "skills" / "lm": ROOT / "skills" / "lm",
            self.home / ".gemini" / "skills" / "lm": ROOT / "skills" / "lm",
        }

    def lm(self, *args, path=None):
        env = {**os.environ, "HOME": str(self.home),
               "PATH": str(self.bin) if path is None else path}
        p = subprocess.run([sys.executable, "-m", "lm", "install", *args],
                           cwd=ROOT, env=env, capture_output=True, text=True)
        return p.returncode, p.stdout, p.stderr

    def test_install_links_and_second_run_is_ok(self):
        rc, out, err = self.lm()
        self.assertEqual((rc, err), (0, ""))
        self.assertEqual(set(out.splitlines()), {f"linked {p}" for p in self.links})
        for link, target in self.links.items():
            self.assertTrue(link.is_symlink())
            self.assertTrue(Path(os.readlink(link)).is_absolute())
            self.assertEqual(link.resolve(), target.resolve())
        rc, out, err = self.lm()
        self.assertEqual((rc, err), (0, ""))
        self.assertEqual(set(out.splitlines()), {f"ok {p}" for p in self.links})

    def test_missing_agent_is_skipped(self):
        root = self.home / ".codex"
        root.rmdir()
        rc, out, err = self.lm()
        self.assertEqual((rc, err), (0, ""))
        skills = self.home / ".agents" / "skills"
        self.assertIn(f"skip {skills} (no {root})", out.splitlines())
        self.assertFalse(skills.exists())

    def test_conflict_file_is_untouched(self):
        self.bin.mkdir(parents=True)
        link = self.bin / "lm"
        link.write_text("keep me")
        rc, out, _ = self.lm()
        self.assertEqual(rc, 1)
        self.assertIn(f"conflict {link}", out.splitlines())
        self.assertEqual(link.read_text(), "keep me")
        self.assertTrue((self.home / ".agents" / "skills" / "lm").is_symlink())

    def test_foreign_and_dangling_symlinks_are_conflicts(self):
        self.bin.mkdir(parents=True)
        link = self.bin / "lm"
        foreign = self.home / "foreign"
        foreign.write_text("foreign")
        link.symlink_to(foreign)
        for dangling in (False, True):
            with self.subTest(dangling=dangling):
                if dangling:
                    foreign.unlink()
                rc, out, _ = self.lm()
                self.assertEqual(rc, 1)
                self.assertIn(f"conflict {link}", out.splitlines())
                self.assertTrue(link.is_symlink())
                self.assertEqual(os.readlink(link), str(foreign))

    def test_conflict_directory_is_untouched(self):
        link = self.bin / "lm"
        link.mkdir(parents=True)
        rc, out, _ = self.lm()
        self.assertEqual(rc, 1)
        self.assertIn(f"conflict {link}", out.splitlines())
        self.assertTrue(link.is_dir())
        self.assertFalse(link.is_symlink())

    def test_uninstall_removes_only_our_links(self):
        self.assertEqual(self.lm()[0], 0)
        foreign_link = self.home / ".claude" / "skills" / "lm"
        foreign_link.unlink()
        foreign_link.symlink_to(self.home / "foreign")
        file_link = self.home / ".agents" / "skills" / "lm"
        file_link.unlink()
        file_link.write_text("keep me")
        rc, out, err = self.lm("--uninstall", path="")
        self.assertEqual((rc, err), (1, ""))
        self.assertIn(f"conflict {foreign_link}", out.splitlines())
        self.assertIn(f"conflict {file_link}", out.splitlines())
        self.assertEqual(file_link.read_text(), "keep me")
        self.assertTrue(foreign_link.is_symlink())
        for link in (self.bin / "lm", self.home / ".gemini" / "skills" / "lm"):
            self.assertIn(f"removed {link}", out.splitlines())
            self.assertFalse(link.is_symlink())

    def test_uninstall_absent_links_creates_no_directories(self):
        rc, out, err = self.lm("--uninstall", path="")
        self.assertEqual((rc, err), (0, ""))
        self.assertEqual(set(out.splitlines()), {f"absent {p}" for p in self.links})
        for link in self.links:
            self.assertFalse(link.parent.exists())

    def test_custom_bin(self):
        custom = self.home / "custom" / "bin"
        rc, out, err = self.lm("--bin", str(custom), path=str(custom))
        self.assertEqual((rc, err), (0, ""))
        link = custom / "lm"
        self.assertIn(f"linked {link}", out.splitlines())
        self.assertEqual(link.resolve(), (ROOT / "bin" / "lm").resolve())
        self.assertFalse(self.bin.exists())
        rc, out, err = self.lm("--bin", str(custom), "--uninstall", path="")
        self.assertEqual((rc, err), (0, ""))
        self.assertIn(f"removed {link}", out.splitlines())
        self.assertFalse(link.is_symlink())

    def test_usage_errors(self):
        for args in (("--bogus",), ("--bin",), ("extra",),
                     ("--bin", "--uninstall"), ("--uninstall", "extra")):
            with self.subTest(args=args):
                rc, out, err = self.lm(*args)
                self.assertEqual(rc, 3)
                self.assertEqual(out, "")
                self.assertIn("usage: lm install [--bin DIR] [--uninstall]", err)
                self.assertFalse(self.bin.exists())

    def test_path_warning(self):
        rc, _, err = self.lm(path="")
        self.assertEqual(rc, 0)
        self.assertIn("warning", err.lower())
        self.assertIn(str(self.bin), err)
        self.assertIn("PATH", err)
        rc, _, err = self.lm(path=os.pathsep.join(("/usr/bin", str(self.bin))))
        self.assertEqual((rc, err), (0, ""))

    def test_path_entries_are_resolved(self):
        self.bin.mkdir(parents=True)
        alias = self.home / "bin-alias"
        alias.symlink_to(self.bin, target_is_directory=True)
        rc, _, err = self.lm(path=str(alias))
        self.assertEqual((rc, err), (0, ""))

    def test_oserror_is_reported(self):
        blocked = self.home / "blocked"
        blocked.write_text("keep me")
        rc, _, err = self.lm("--bin", str(blocked / "bin"))
        self.assertEqual(rc, 1)
        self.assertIn("lm install:", err)
        self.assertEqual(blocked.read_text(), "keep me")

    def test_skill_frontmatter_and_size(self):
        data = (ROOT / "skills" / "lm" / "SKILL.md").read_bytes()
        lines = data.decode("utf-8").splitlines()
        self.assertEqual(lines[0], "---")
        end = lines.index("---", 1)
        frontmatter = lines[1:end]
        self.assertIn("name: lm", frontmatter)
        self.assertTrue(any(line.startswith("description:") for line in frontmatter))
        self.assertLessEqual(len(lines), 30)
        self.assertLessEqual(len(data), 2500)


if __name__ == "__main__":
    unittest.main()
