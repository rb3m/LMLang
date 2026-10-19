import difflib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from lm.check import Checker
from lm.edit import get_at, locate
from lm.loader import load
from lm.sexpr import Atom, SList

ROOT = Path(__file__).resolve().parents[2]

APP = '''(module app
  (purpose "Uses shapes and billing.")
  (use billing shapes)
  (export side total-cents)
  (fn safe-total
    (purpose "Total or zero when the region is unknown.")
    (sig (cents (List Int)) -> Int)
    (example ((list 100 200)) => 348)
    (body (try (billing.total cents "MX") (catch billing.BadRegion (r) 0))))
  (fn side
    (purpose "Longest side of a square.")
    (sig (n Int) -> Int)
    (example (4) => 4)
    (body (shapes.longest-side (shapes.Rect n n))))
  (fn total-cents
    (purpose "Area of a circle.")
    (sig (s shapes.Shape) -> Float)
    (example ((shapes.Circle 2)) => 12.566370614359172)
    (body (shapes.area s))))
'''


class Project:
    def __init__(self):
        self.dir = Path(tempfile.mkdtemp())
        (self.dir / "src").mkdir()
        for n in ("billing", "shapes"):
            shutil.copy(ROOT / f"examples/{n}.lm", self.dir / "src")
        (self.dir / "src/app.lm").write_text(APP)

    def lm(self, *args):
        env = dict(os.environ, PYTHONPATH=str(ROOT))
        p = subprocess.run([sys.executable, "-m", "lm", *args], cwd=self.dir, capture_output=True, text=True, env=env)
        return p.returncode, p.stdout, p.stderr

    def text(self, n):
        return (self.dir / "src" / f"{n}.lm").read_text()

    def codes(self, out):
        return sorted({json.loads(l)["code"] for l in out.splitlines() if l.startswith("{")})


class EditOps(unittest.TestCase):
    def setUp(self):
        self.p = Project()
        self.assertEqual(self.p.lm("check")[0], 0)
        self.assertEqual(self.p.lm("test")[0], 0)

    def test_replace_body_is_a_minimal_diff(self):
        before = self.p.text("shapes")
        rc, out, _ = self.p.lm("edit", "replace-body", "shapes.longest-side", "(match s ((Circle r) (+ r r)) ((Rect w h) (math.max h w)) (Empty 0))")
        self.assertEqual((rc, out), (0, ""))
        after = self.p.text("shapes")
        changed = [l for l in difflib.unified_diff(before.splitlines(), after.splitlines(), lineterm="", n=0) if l[:1] in "+-" and l[:3] not in ("+++", "---")]
        self.assertLessEqual(len(changed), 2, changed)
        self.assertEqual(self.p.lm("test")[0], 0)

    def test_replace_body_type_error_is_reported_with_path(self):
        rc, out, _ = self.p.lm("edit", "replace-body", "shapes.longest-side", '"x"')
        self.assertEqual(rc, 1)
        d = [json.loads(l) for l in out.splitlines() if "E-TYPE" in l][0]
        self.assertEqual(d["path"], "shapes/longest-side/body/1")
        self.assertIn('(body "x")', self.p.text("shapes"))

    def test_add_decl_keeps_sorted_order_and_rejects_duplicates(self):
        rc, _, _ = self.p.lm("edit", "add-decl", "shapes", '(fn double (purpose "Twice n.") (sig (n Int) -> Int) (example (2) => 4) (body (* n 2)))')
        self.assertEqual(rc, 0)
        t = self.p.text("shapes")
        self.assertLess(t.index("(fn describe"), t.index("(fn double"))
        self.assertLess(t.index("(fn double"), t.index("(fn longest-side"))
        before = self.p.text("shapes")
        rc, _, err = self.p.lm("edit", "add-decl", "shapes", '(fn double (purpose "x") (sig (n Int) -> Int) (body n))')
        self.assertEqual(rc, 1)
        self.assertIn("refused", err)
        self.assertEqual(self.p.text("shapes"), before)

    def test_remove_fn_guards_callers(self):
        before = self.p.text("shapes")
        rc, _, err = self.p.lm("edit", "remove-fn", "shapes.area")
        self.assertEqual(rc, 1)
        self.assertIn("app.total-cents", err)
        self.assertEqual(self.p.text("shapes"), before)
        rc, out, _ = self.p.lm("edit", "remove-fn", "shapes.area", "--force")
        self.assertEqual(rc, 1)  # app now has an unresolved name
        self.assertIn("E-NAME-UNRESOLVED", self.p.codes(out))
        self.assertNotIn("area", self.p.text("shapes"))

    def test_rename_fn_updates_definition_export_and_callers(self):
        rc, out, _ = self.p.lm("edit", "rename", "shapes.area", "surface")
        self.assertEqual((rc, out), (0, ""))
        self.assertIn("shapes.surface", self.p.text("app"))
        self.assertIn("(export Shape describe longest-side scale surface)", self.p.text("shapes"))
        self.assertNotIn("(fn area", self.p.text("shapes"))
        self.assertEqual(self.p.lm("test")[0], 0)

    def test_rename_type_and_error_follow_qualified_references(self):
        self.assertEqual(self.p.lm("edit", "rename", "shapes.Shape", "Form")[0], 0)
        self.assertIn("(s shapes.Form)", self.p.text("app"))
        self.assertEqual(self.p.lm("edit", "rename", "billing.BadRegion", "billing.UnknownRegion")[0], 0)
        self.assertIn("(catch billing.UnknownRegion (r) 0)", self.p.text("app"))
        self.assertIn('(fail UnknownRegion "XX")', self.p.text("billing"))
        self.assertEqual(self.p.lm("test")[0], 0)

    def test_rename_type_used_in_fields(self):
        (self.p.dir / "src/rec.lm").write_text('''(module rec
  (purpose "p")
  (type Item (rec (k Str)))
  (type Shape (sum (One (it Item)) Two))
  (type Wrap (rec (n Int) (it Item)))
  (error Bad (n Int) (it Item)))
''')
        self.assertEqual(self.p.lm("edit", "rename", "rec.Item", "Thing")[0], 0)
        self.assertEqual(self.p.text("rec"), '''(module rec
  (purpose "p")
  (type Shape (sum (One (it Thing)) Two))
  (type Thing (rec (k Str)))
  (type Wrap (rec (n Int) (it Thing)))
  (error Bad (n Int) (it Thing)))
''')

    def test_rename_rolls_back_when_it_would_introduce_errors(self):
        before = {n: self.p.text(n) for n in ("app", "shapes", "billing")}
        rc, out, err = self.p.lm("edit", "rename", "shapes.area", "len")  # `len` is a prelude name
        self.assertEqual(rc, 1)
        self.assertIn("aborted", err)
        self.assertEqual({n: self.p.text(n) for n in before}, before)
        rc, _, err = self.p.lm("edit", "rename", "shapes.area", "describe")
        self.assertEqual(rc, 1)
        self.assertEqual({n: self.p.text(n) for n in before}, before)

    def test_set_purpose_and_sig(self):
        self.assertEqual(self.p.lm("edit", "set-purpose", "shapes.area", "Area with pi = 3.")[0], 0)
        self.assertIn('(purpose "Area with pi = 3.")', self.p.text("shapes"))
        self.assertEqual(self.p.lm("edit", "set-purpose", "shapes", "Shape helpers.")[0], 0)
        rc, out, _ = self.p.lm("edit", "set-purpose", "shapes.area", "x" * 120)
        self.assertEqual((rc, self.p.codes(out)), (1, ["E-PURPOSE-LONG"]))
        self.p.lm("edit", "set-purpose", "shapes.area", "ok")
        rc, out, _ = self.p.lm("edit", "set-sig", "shapes.scale", "(sig (s Shape) (k Str) -> Shape)")
        self.assertEqual((rc, "E-TYPE" in self.p.codes(out)), (1, True))

    def test_use_and_export_ops_are_idempotent(self):
        self.assertEqual(self.p.lm("edit", "remove-use", "app", "billing")[0], 1)  # still referenced
        self.assertIn("E-USE-MISSING", self.p.codes(self.p.lm("check")[1]))
        self.assertEqual(self.p.lm("edit", "add-use", "app", "billing")[0], 0)
        t = self.p.text("app")
        self.assertEqual(self.p.lm("edit", "add-use", "app", "billing")[0], 0)
        self.assertEqual(self.p.text("app"), t)
        self.assertEqual(self.p.lm("edit", "add-export", "app", "safe-total")[0], 0)
        self.assertIn("safe-total", self.p.text("app").split("(fn")[0])

    def test_add_export_refused_on_module_without_export_clause(self):
        (self.p.dir / "src/noexp.lm").write_text('(module noexp\n  (purpose "No export clause.")\n  (fn foo\n    (purpose "Foo.")\n    (sig -> Int)\n    (body 1)))\n')
        rc, _, err = self.p.lm("edit", "add-export", "noexp", "foo")
        self.assertEqual(rc, 1)
        self.assertIn("has no export clause (everything is already exported)", err)

    def test_dry_run_prints_diff_and_writes_nothing(self):
        before = self.p.text("shapes")
        rc, out, _ = self.p.lm("edit", "rename", "shapes.area", "surface", "--dry-run")
        self.assertEqual(rc, 0)
        self.assertIn("+  (fn surface", out)
        self.assertEqual(self.p.text("shapes"), before)

    def test_add_eff_fails_example(self):
        self.assertEqual(self.p.lm("edit", "add-fails", "app.side", "DivZero")[0], 0)
        self.assertIn("W-FAILS-UNUSED", self.p.codes(self.p.lm("check")[1]))
        self.assertEqual(self.p.lm("edit", "add-example", "app.side", "(example (7) => 7)")[0], 0)
        self.assertIn("(example (7) => 7)", self.p.text("app"))

    def test_usage_errors(self):
        for args in (["edit"], ["edit", "bogus"], ["edit", "rename", "x"], ["edit", "apply", "{bad"], ["edit", "rename", "a.b", "c", "--in", "nowhere"]):
            self.assertEqual(self.p.lm(*args)[0], 3, args)


class DiagnosticFixLoop(unittest.TestCase):
    """check -> take the fix a diagnostic offers -> `edit apply` -> that diagnostic disappears."""

    CASES = [("effect-undeclared", "E-EFFECT-UNDECLARED"), ("use-missing", "E-USE-MISSING"), ("unresolved-qualified", "E-NAME-UNRESOLVED"),
             ("fails-undeclared", "E-FAILS-UNDECLARED"), ("noncanonical", "E-NONCANONICAL"), ("use-unused", "W-USE-UNUSED")]

    def test_each_fix_resolves_its_diagnostic(self):
        for name, code in self.CASES:
            p = Project()
            for n in ("billing", "shapes", "app"):
                (p.dir / f"src/{n}.lm").unlink()
            shutil.copy(ROOT / f"tests/spec/check/{name}.lm", p.dir / "src")
            _, out, _ = p.lm("check")
            ds = [json.loads(l) for l in out.splitlines() if l.startswith("{")]
            d = next(d for d in ds if d["code"] == code)
            self.assertTrue(d["fix"], (name, d))
            rc, _, err = p.lm("edit", "apply", json.dumps(d["fix"]))
            self.assertIn(rc, (0, 1), (name, err))
            _, out2, _ = p.lm("check")
            self.assertNotIn(code, p.codes(out2), name)


class RefPathsAreAddressable(unittest.TestCase):
    def test_every_recorded_ref_path_locates_a_node(self):
        for target in [ROOT / "stdlib", ROOT / "examples", ROOT / "tests/spec/check/ok-basic.lm", ROOT / "tests/spec/run/semantics.lm"]:
            prog = load([str(target)])
            ck = Checker(prog)
            ck.check_all = True
            ck.run()
            self.assertTrue(prog.refs)
            for (mn, path), tgt in prog.refs.items():
                if mn in prog.modules and prog.modules[mn].is_target:
                    node = get_at(prog.modules[mn].root, locate(prog.modules[mn].root, path.split("/")))
                    self.assertIsInstance(node, (Atom, SList), (mn, path))
                    if isinstance(node, Atom) and node.kind in ("sym", "type"):
                        self.assertTrue(node.value.split(".")[-1] == tgt.split(".")[-1] or tgt.startswith("prelude.") or node.kind == "type", (mn, path, node.value, tgt))


class VariantRename(unittest.TestCase):
    def setUp(self):
        self.p = Project()
        self.assertEqual(self.p.lm("check")[0], 0)
        self.assertEqual(self.p.lm("test")[0], 0)

    def test_spelling_mod_type_variant_is_usage_error(self):
        rc, _, err = self.p.lm("edit", "rename", "shapes.Shape.Circle", "Disc")
        self.assertEqual(rc, 3)
        self.assertIn("write 'shapes.Circle' instead of 'shapes.Shape.Circle'", err)
        rc, _, err = self.p.lm("edit", "rename", "Shape.Circle", "Disc")
        self.assertEqual(rc, 3)
        self.assertIn("write 'mod.Circle' instead of 'Shape.Circle'", err)

    def test_collision_and_invalid_name_refused(self):
        before = self.p.text("shapes")
        rc, _, err = self.p.lm("edit", "rename", "shapes.Circle", "Rect")
        self.assertEqual(rc, 1)
        self.assertIn("collides", err)
        self.assertEqual(self.p.text("shapes"), before)

        rc, _, err = self.p.lm("edit", "rename", "shapes.Circle", "Shape")
        self.assertEqual(rc, 1)
        self.assertIn("collides", err)
        self.assertEqual(self.p.text("shapes"), before)

        rc, _, err = self.p.lm("edit", "rename", "shapes.Circle", "Some")
        self.assertEqual(rc, 1)
        self.assertIn("collides", err)
        self.assertEqual(self.p.text("shapes"), before)

        rc, _, err = self.p.lm("edit", "rename", "shapes.Circle", "disc")
        self.assertEqual(rc, 1)
        self.assertIn("not a valid Capitalized name", err)
        self.assertEqual(self.p.text("shapes"), before)

    def test_rename_across_two_modules_with_patterns_and_constructors(self):
        rc, out, err = self.p.lm("edit", "rename", "shapes.Circle", "Disc")
        self.assertEqual((rc, out), (0, ""))
        shapes_txt = self.p.text("shapes")
        self.assertIn("(type Shape (sum (Disc (r Int)) (Rect (w Int) (h Int)) Empty))", shapes_txt)
        self.assertIn("(example ((Disc 2)) => 12.566370614359172)", shapes_txt)
        self.assertIn("((Disc r) (* (float.pi) (float.from-int (* r r))))", shapes_txt)
        self.assertIn("(Disc (* r k))", shapes_txt)
        self.assertNotIn("Circle", shapes_txt)

        app_txt = self.p.text("app")
        self.assertIn("(example ((shapes.Disc 2)) => 12.566370614359172)", app_txt)
        self.assertNotIn("shapes.Circle", app_txt)

        self.assertEqual(self.p.lm("check")[0], 0)
        self.assertEqual(self.p.lm("test")[0], 0)

        # Now rename the 0-arg variant Empty -> Void
        rc, out, _ = self.p.lm("edit", "rename", "shapes.Empty", "Void")
        self.assertEqual((rc, out), (0, ""))
        shapes_txt2 = self.p.text("shapes")
        self.assertIn("(type Shape (sum (Disc (r Int)) (Rect (w Int) (h Int)) Void))", shapes_txt2)
        self.assertIn("(example (Void) => 0)", shapes_txt2)
        self.assertIn("(Void 0)", shapes_txt2)
        self.assertIn("(Void Void)", shapes_txt2)
        self.assertNotIn("Empty", shapes_txt2)
        self.assertEqual(self.p.lm("check")[0], 0)
        self.assertEqual(self.p.lm("test")[0], 0)

    def test_scenario_reference_refused_without_force_and_updated_with_force(self):
        accept_dir = self.p.dir / "tests/accept"
        accept_dir.mkdir(parents=True)
        accept_file = accept_dir / "shapes.accept"
        accept_file.write_text('''(scenarios
  (scenario "Circle area"
    (status approved)
    (why "Area of a circle shapes.Circle.")
    (run app.total-cents (shapes.Circle 2))
    (expect 12))
  (scenario "Untouched rect"
    (status approved)
    (why "Unrelated.")
    (run app.side 4)
    (expect 4)))
''')
        # Create accept.lock with both scenarios approved
        from lm.accept import load_scenarios
        scs, _ = load_scenarios(str(accept_dir))
        sc_map = {s.name: s.digest() for s in scs}
        lock_file = self.p.dir / "accept.lock"
        lock_file.write_text(f"{sc_map['Circle area']} Circle area\n{sc_map['Untouched rect']} Untouched rect\n")

        # Verify guard is OK initially
        self.assertEqual(self.p.lm("accept", "--guard")[0], 0)

        # Rename without --force: refused
        before_accept = accept_file.read_text()
        before_shapes = self.p.text("shapes")
        rc, _, err = self.p.lm("edit", "rename", "shapes.Circle", "Disc")
        self.assertEqual(rc, 1)
        self.assertIn("Circle area", err)
        self.assertIn("--force", err)
        self.assertEqual(accept_file.read_text(), before_accept)
        self.assertEqual(self.p.text("shapes"), before_shapes)

        # Rename with --dry-run and --force: prints diff, writes nothing
        rc, out, _ = self.p.lm("edit", "rename", "shapes.Circle", "Disc", "--force", "--dry-run")
        self.assertEqual(rc, 0)
        self.assertIn("+    (run app.total-cents (shapes.Disc 2))", out)
        self.assertIn("+  (type Shape (sum (Disc (r Int))", out)
        self.assertEqual(accept_file.read_text(), before_accept)
        self.assertEqual(self.p.text("shapes"), before_shapes)

        # Rename with --force: succeeds
        rc, _, _ = self.p.lm("edit", "rename", "shapes.Circle", "Disc", "--force")
        self.assertEqual(rc, 0)
        after_accept = accept_file.read_text()
        self.assertIn("(run app.total-cents (shapes.Disc 2))", after_accept)
        self.assertIn("(status proposed)", after_accept)
        # Untouched rect scenario kept its status
        self.assertIn('(scenario "Untouched rect"\n    (status approved)', after_accept)
        # String literal in why was NOT changed
        self.assertIn('"Area of a circle shapes.Circle."', after_accept)
        # Lock file was untouched
        self.assertEqual(lock_file.read_text(), f"{sc_map['Circle area']} Circle area\n{sc_map['Untouched rect']} Untouched rect\n")

        # Guard now reports Circle area as unapproved
        rc_guard, out_guard, _ = self.p.lm("accept", "--guard")
        self.assertEqual(rc_guard, 1)
        self.assertIn("UNAPPROVED Circle area: locked scenario is no longer approved", out_guard)


if __name__ == "__main__":
    unittest.main()

