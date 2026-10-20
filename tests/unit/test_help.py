"""Public command discovery and registry drift checks."""
import ast
import re
import subprocess
import sys
import unittest
from pathlib import Path

from lm import __version__
from lm.commands import COMMANDS, USAGE

ROOT = Path(__file__).resolve().parents[2]


def lm(*args):
    return subprocess.run(
        [sys.executable, "-m", "lm", *args], cwd=ROOT,
        capture_output=True, text=True,
    )


class HelpTests(unittest.TestCase):
    def test_usage_aliases(self):
        for alias in ("help", "--help", "-h"):
            with self.subTest(alias=alias):
                result = lm(alias)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stderr, "")
                self.assertEqual(result.stdout, USAGE)
                for command in COMMANDS.values():
                    self.assertIn(f"lm {command.synopsis}\n", result.stdout)
                    self.assertIn(command.summary, result.stdout)
                self.assertTrue(result.stdout.endswith(
                    "3 usage / 70 runtime fault\n"))

    def test_individual_help(self):
        for command in COMMANDS.values():
            with self.subTest(command=command.name):
                result = lm("help", command.name)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stderr, "")
                self.assertIn(command.synopsis, result.stdout)
                self.assertIn(command.summary, result.stdout)

    def test_edit_operations_match_spec(self):
        spec = (ROOT / "docs/SPEC.md").read_text()
        section = spec.split("## 15.", 1)[1].split("## 16.", 1)[0]
        operations = []
        for line in section.splitlines():
            if line.startswith("| `"):
                operations.extend(re.findall(r"`([^`]+)`", line.split("|")[1]))
        self.assertTrue(operations)
        result = lm("help", "edit")
        self.assertEqual(result.returncode, 0, result.stderr)
        rows = [line.strip().split(" | ")
                for line in result.stdout.splitlines()
                if " | " in line and not line.strip().startswith("op |")]
        self.assertEqual(set(operations), {row[0] for row in rows})
        self.assertTrue(all(len(row) == 3 and all(row) for row in rows))

    def test_unknown_command_and_no_arguments(self):
        for args in (("no-such-command",), ("help", "no-such-command")):
            result = lm(*args)
            self.assertEqual(result.returncode, 3)
            self.assertEqual(result.stdout, "")
            self.assertEqual(result.stderr,
                             "lm: unknown command `no-such-command`\n" + USAGE)
        result = lm()
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (3, "", USAGE))

    def test_version(self):
        for alias in ("--version", "-V"):
            result = lm(alias)
            self.assertEqual((result.returncode, result.stdout, result.stderr),
                             (0, f"lm {__version__}\n", ""))

    def test_guide(self):
        result = lm("guide")
        self.assertEqual((result.returncode, result.stderr), (0, ""))
        self.assertIn("Workflow", result.stdout)
        self.assertNotIn("docs/", result.stdout)
        self.assertEqual(result.stdout, (ROOT / "lm/guide.md").read_text())
        self.assertLessEqual(len(result.stdout.encode()), 9 * 1024)

    def test_extra_arguments(self):
        for args in (("guide", "extra"), ("help", "edit", "extra"),
                     ("--version", "extra")):
            result = lm(*args)
            self.assertEqual(result.returncode, 3)
            self.assertEqual(result.stdout, "")
            self.assertIn("usage:", result.stderr)

    def test_registry_is_documented_and_flags_exist_in_handlers(self):
        docs = (ROOT / "docs/COMMANDS.md").read_text()
        for name, command in COMMANDS.items():
            with self.subTest(command=name):
                self.assertEqual(name, command.name)
                self.assertRegex(docs, rf"`{name}(?:[ `])")
                module, function = command.handler.split(":")
                source = ROOT.joinpath(*module.split(".")).with_suffix(".py")
                tree = ast.parse(source.read_text())
                self.assertTrue(any(isinstance(node, ast.FunctionDef)
                                    and node.name == function
                                    for node in tree.body))
                # Server entry parsing is shared with standalone Python builds.
                trees = [tree]
                if name == "serve":
                    trees.append(ast.parse(
                        (ROOT / "lm/serve_options.py").read_text()))
                literals = [node.value for tree in trees for node in ast.walk(tree)
                            if isinstance(node, ast.Constant)
                            and isinstance(node.value, str)]
                for flag in re.findall(r"--[a-z][a-z-]*", command.synopsis):
                    self.assertIn(flag, docs)
                    self.assertTrue(any(flag in value for value in literals),
                                    f"{flag} missing from {module} literals")
