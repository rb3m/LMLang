"""Public export tests use disposable commits, never the working checkout's index."""
from pathlib import Path
import os
import importlib.util
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/export-public.sh"


@unittest.skipUnless(shutil.which("git"), "git unavailable")
class ExportPublicTests(unittest.TestCase):
    def setUp(self):
        if subprocess.run(["git", "rev-parse", "--is-inside-work-tree"], cwd=ROOT,
                          capture_output=True).returncode:
            self.skipTest("not a git checkout")

    def run_export(self, root, dest=".", scan=False):
        return subprocess.run([str(root / "scripts/export-public.sh"), str(dest)]
                              + (["--scan-only"] if scan else []), cwd=root,
                              capture_output=True, text=True)

    def snapshot(self, temp):
        """Include new release files as well as tracked working-tree contents."""
        root = Path(temp) / "source"
        root.mkdir()
        names = subprocess.check_output(["git", "ls-files", "-z", "--cached", "--others",
                                         "--exclude-standard"], cwd=ROOT).split(b"\0")
        for name in names:
            if not name:
                continue
            rel = Path(os.fsdecode(name))
            source = ROOT / rel
            target = root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            if source.is_symlink():
                target.symlink_to(os.readlink(source))
            else:
                shutil.copy2(source, target)
        self.git(root, "init", "-q")
        self.git(root, "add", "-A")
        self.git(root, "-c", "user.name=Export Test", "-c", "user.email=test@users.noreply.github.com",
                 "-c", "commit.gpgsign=false", "commit", "-qm", "Disposable export fixture")
        return root

    def git(self, root, *args):
        return subprocess.check_output(["git", "-C", str(root), *args], stderr=subprocess.STDOUT)

    def test_scan_checkout(self):
        result = self.run_export(ROOT, scan=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_full_export(self):
        with tempfile.TemporaryDirectory() as temp:
            root = self.snapshot(temp)
            dest = Path(temp) / "public"
            result = self.run_export(root, dest)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertFalse((dest / "docs/ENVIRONMENT.md").exists())
            self.assertTrue((dest / "LICENSE").is_file())
            self.assertFalse((dest / ".git").exists())
            # Existing destination repositories keep their history and untracked files.
            self.git(dest, "init", "-q")
            self.git(dest, "add", "-A")
            (dest / "local-note").write_text("Keep this untracked file.\n")
            config = (dest / ".git/config").read_bytes()
            result = self.run_export(root, dest)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual((dest / ".git/config").read_bytes(), config)
            self.assertTrue((dest / "local-note").exists())
            (root / "README.md").write_text("changed\n")
            result = self.run_export(root, Path(temp) / "dirty-export")
            self.assertEqual(result.returncode, 1)
            self.assertIn("uncommitted", result.stderr)

    def test_refuses_untracked_destination_symlink(self):
        spec = importlib.util.spec_from_file_location("export_public", ROOT / "scripts/export_public.py")
        exporter = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(exporter)
        with tempfile.TemporaryDirectory() as temp:
            stage = Path(temp) / "stage"
            stage.mkdir()
            (stage / "README.md").write_text("Public content.\n")
            dest = Path(temp) / "public"
            dest.mkdir()
            self.git(dest, "init", "-q")
            outside = Path(temp) / "outside"
            outside.mkdir()
            (dest / "README.md").symlink_to(outside, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, "untracked path obstructed"):
                exporter.sync(stage, dest, ROOT)
            self.assertEqual(list(outside.iterdir()), [])
            self.assertTrue((dest / "README.md").is_symlink())

    def test_exclusion_refuses_symlink_ancestor(self):
        with tempfile.TemporaryDirectory() as temp:
            root = self.snapshot(temp)
            outside = Path(temp) / "outside"
            outside.mkdir()
            sentinel = outside / "ENVIRONMENT.md"
            sentinel.write_text("Must remain intact.\n")
            shutil.rmtree(root / "docs")
            (root / "docs").symlink_to(outside, target_is_directory=True)
            self.git(root, "add", "-A")
            self.git(root, "-c", "user.name=Export Test",
                     "-c", "user.email=test@users.noreply.github.com",
                     "-c", "commit.gpgsign=false", "commit", "-qm", "Symlink fixture")
            result = self.run_export(root, Path(temp) / "public")
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn("export-public:", result.stderr)
            self.assertEqual(sentinel.read_text(), "Must remain intact.\n")

    def test_scan_rejects_private_data(self):
        with tempfile.TemporaryDirectory() as temp:
            root = self.snapshot(temp)
            (root / "leak.txt").write_text("192.168." + "1.1\n" + "private" + "@gmail.com\n")
            self.git(root, "add", "leak.txt")
            result = self.run_export(root, scan=True)
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn("leak.txt:1:", result.stdout)
            self.assertIn("leak.txt:2:", result.stdout)


if __name__ == "__main__":
    unittest.main()
