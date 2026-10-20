"""Actionable export and binding diagnostics, and str.cat build parity."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from lm.build import find_go
from lm.check import Checker
from lm.loader import load

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "tests/spec/check"
RESULT = "`result` is reserved (bound to the return value in `ensures`); rename it, e.g. `res`"


def cli(cwd, *args):
    return subprocess.run([sys.executable, "-m", "lm", *args], cwd=cwd,
                          env={**os.environ, "PYTHONPATH": str(ROOT)},
                          capture_output=True, text=True)


class Diagnostics(unittest.TestCase):
    def test_export_variant_fix(self):
        for exports in ("Choice", "Choice Options", "Options Choice"):
            with self.subTest(exports=exports), tempfile.TemporaryDirectory() as tmp:
                src = Path(tmp) / "src"
                src.mkdir()
                text = (CHECK / "export-variant.lm").read_text()
                (src / "export-variant.lm").write_text(text.replace("(export Choice)", f"(export {exports})"))
                p = cli(tmp, "check")
                self.assertEqual(p.returncode, 1, p.stderr)
                d = next(json.loads(s) for s in p.stdout.splitlines() if 'E-NAME-UNRESOLVED' in s)
                self.assertEqual(d["msg"], "export `Choice`: a variant of `Options`; export `Options` (exports its variants)")
                self.assertEqual((d["expected"], d["found"]), ("Options", "Choice"))
                if "Options" in exports:
                    # No remove-export/atom operation is currently available.
                    self.assertFalse(d["fix"])
                    continue
                self.assertTrue(d["fix"])
                p = cli(tmp, "edit", "apply", json.dumps(d["fix"]))
                self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
                p = cli(tmp, "check")
                self.assertEqual(p.returncode, 0, p.stdout + p.stderr)

    def test_unknown_export_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "unknown.lm"
            p.write_text('(module unknown (purpose "Unknown export.") (export Missing))')
            prog = load([str(p)])
            Checker(prog).run()
            d = next(d for d in prog.diags if d.code == "E-NAME-UNRESOLVED")
            self.assertEqual(d.msg, "export `Missing`: no such type or error")

    def test_result_parameter_message(self):
        prog = load([str(CHECK / "dup-result-param.lm")])
        Checker(prog).run()
        self.assertEqual([d.msg for d in prog.diags if d.code == "E-DUP-NAME"], [RESULT])

    def test_local_collision_messages(self):
        prog = load([str(CHECK / "dup-result-param.lm")])
        ck = Checker(prog)
        ck.run()
        m = prog.modules["dup-result-param"]
        cases = [
            ("result", {}, None, RESULT),
            ("if", {}, None, "`if` collides with a reserved word"),
            ("pair", {}, None, "`pair` collides with a reserved word; `pair` is the prelude pair constructor, name it `p` instead"),
            ("value", {}, None, "`value` collides with a function of this module"),
            ("limit", {}, None, "`limit` collides with a constant of this module"),
            ("x", {"x": None}, None, "`x` collides with a binding already in scope"),
            ("x", {}, {"x"}, "`x` collides with a binding already introduced here"),
        ]
        m.consts["limit"] = None
        for name, env, extra, msg in cases:
            with self.subTest(name=name, env=env, extra=extra):
                self.assertFalse(ck.local_ok(m, name, m.root, "test", env, extra))
                self.assertEqual(prog.diags[-1].msg, msg)
        self.assertTrue(ck.local_ok(m, "fresh", m.root, "test", {}, set()))


class CatBuild(unittest.TestCase):
    def check_target(self, target):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            (p / "main.lm").write_text('''(module main
  (purpose "Build string concatenation through stdlib.")
  (use io str)
  (fn main
    (purpose "Print concatenated strings and the empty case.")
    (sig -> Unit)
    (eff io.out)
    (body (do (io.print (str.cat (list "a" "b" "c"))) (io.print (str.cat (list)))))))
''')
            exe = p / "app"
            built = cli(tmp, "build", "--target", target, "main.main", "main.lm", "-o", str(exe))
            self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
            ran = subprocess.run([str(exe)], cwd=tmp, capture_output=True, text=True)
            self.assertEqual((ran.returncode, ran.stdout, ran.stderr), (0, "abc\n\n", ""))

    def test_python(self):
        self.check_target("py")

    def test_go(self):
        if find_go() is None:
            sys.stderr.write("\nSKIP: Go toolchain unavailable (str.cat build)\n")
            self.skipTest("Go toolchain unavailable")
        self.check_target("go")
