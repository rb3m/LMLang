import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from golden_support import golden_command

from lm import accept as A

ROOT = Path(__file__).resolve().parents[2]
GOLDEN = ROOT / "tests" / "golden"

HELLO = '''(module hello
  (purpose "Greets.")
  (use io)
  (export greet)
  (fn greet
    (purpose "Print a greeting.")
    (sig (name Str) -> Unit)
    (eff io.out)
    (body (io.print name))))
'''


def scen(name, status="approved", run='(run billing.total (list 100 200) "MX")', expect="(expect 348)", extra=""):
    return f'(scenario "{name}" (status {status}) (why "because") {extra}{run} {expect})'


class Proj:
    def __init__(self, tc):
        self.tc = tc
        self.d = Path(tempfile.mkdtemp())
        tc.addCleanup(shutil.rmtree, self.d, True)
        (self.d / "examples").mkdir()
        for f in ("billing.lm", "shapes.lm"):
            shutil.copy(ROOT / "examples" / f, self.d / "examples" / f)
        (self.d / "tests" / "accept").mkdir(parents=True)

    def write(self, *scs):
        (self.d / "tests/accept/t.accept").write_text("(scenarios " + " ".join(scs) + ")")

    def lm(self, *args):
        env = {**os.environ, "PYTHONPATH": str(ROOT)}
        return subprocess.run([sys.executable, "-m", "lm", *args], cwd=self.d, capture_output=True, text=True, env=env, stdin=subprocess.DEVNULL)

    def bless(self):
        scs, bad = A.load_scenarios(self.d / "tests/accept")
        self.tc.assertEqual(bad, [])
        A.write_lock(self.d / "accept.lock", scs)


class TestAccept(unittest.TestCase):
    def test_pass_fail_proposed(self):
        p = Proj(self)
        p.write(scen("ok"), scen("wrong", expect="(expect 349)"), scen("p", status="proposed"))
        p.bless()
        r = p.lm("accept")
        self.assertEqual(r.returncode, 1)
        self.assertIn("PASS  approved  ok", r.stdout)
        self.assertIn("FAIL  approved  wrong", r.stdout)
        self.assertIn("got 348", r.stdout)
        self.assertIn("proposed  p", r.stdout)
        self.assertIn("2 approved (1 pass, 1 FAIL) · 1 proposed · guard OK", r.stdout)

    def test_unblessed_approved_fails_guard(self):
        p = Proj(self)
        p.write(scen("ok"))
        r = p.lm("accept")
        self.assertEqual(r.returncode, 1)
        self.assertIn("UNBLESSED ok", r.stdout)
        p.bless()
        self.assertEqual(p.lm("accept").returncode, 0)
        self.assertEqual(p.lm("accept", "--guard").returncode, 0)

    def test_changed_and_missing_detected(self):
        p = Proj(self)
        p.write(scen("a"), scen("b"))
        p.bless()
        p.write(scen("a", expect="(expect 999)"))
        r = p.lm("accept", "--guard")
        self.assertEqual(r.returncode, 1)
        self.assertIn("CHANGED   a", r.stdout)
        self.assertIn("MISSING   b", r.stdout)

    def test_unapproving_a_locked_scenario_is_caught(self):
        p = Proj(self)
        p.write(scen("a"))
        p.bless()
        p.write(scen("a", status="proposed"))
        self.assertIn("UNAPPROVED a", p.lm("accept", "--guard").stdout)

    def test_status_does_not_change_digest(self):
        p = Proj(self)
        p.write(scen("a"), scen("a2", status="proposed"))
        s = {x.name: x for x in A.load_scenarios(p.d / "tests/accept")[0]}
        q = Proj(self)
        q.write(scen("a", status="proposed"))
        t = A.load_scenarios(q.d / "tests/accept")[0][0]
        self.assertEqual(s["a"].digest(), t.digest())

    def test_bless_refused_without_terminal(self):
        p = Proj(self)
        p.write(scen("a"))
        r = p.lm("accept", "--bless")
        self.assertEqual(r.returncode, 1)
        self.assertFalse((p.d / "accept.lock").exists())

    def test_bad_scenarios_reported(self):
        p = Proj(self)
        p.write('(scenario "no why" (status approved) (run billing.total (list 1) "MX") (expect 1))',
                '(scenario "bad status" (status maybe) (why "x") (run billing.total (list 1) "MX") (expect 1))',
                scen("type error", expect='(expect "text")'),
                scen("unknown fn", run="(run billing.nope 1)"),
                scen("arity", run="(run billing.total 1)"))
        r = p.lm("accept")
        self.assertEqual(r.returncode, 1)
        self.assertEqual(sum(l.startswith(("BAD ", "FAIL ")) for l in r.stdout.splitlines()), 5, r.stdout)
        self.assertIn("does not type-check", r.stdout)
        self.assertIn("unknown function", r.stdout)

    def test_expect_fail_and_out(self):
        p = Proj(self)
        (p.d / "examples/hello.lm").write_text(HELLO)
        p.write(scen("fails", run='(run billing.total (list 1) "US")', expect='(expect-fail billing.BadRegion "US")'),
                scen("wrong fail", run='(run billing.total (list 1) "US")', expect='(expect-fail billing.BadRegion "MX")'),
                scen("prints", run='(run hello.greet "hi")', expect='(expect-out "hi\\n")', extra="(allow io.out) "),
                scen("denied", run='(run hello.greet "hi")', expect='(expect-out "hi\\n")'))
        p.bless()
        out = p.lm("accept").stdout
        self.assertIn("PASS  approved  fails", out)
        self.assertIn("FAIL  approved  wrong fail", out)
        self.assertIn("PASS  approved  prints", out)
        self.assertIn("FAIL  approved  denied", out)

    def test_review_lists_proposed_with_actuals(self):
        p = Proj(self)
        p.write(scen("p", status="proposed", expect="(expect 1)"))
        out = p.lm("accept", "--review").stdout
        self.assertIn("why: because", out)
        self.assertIn("program today: got 348", out)
        scs, _ = A.load_scenarios(p.d / "tests/accept")
        self.assertIn(f"{scs[0].digest()}  p", out)

    def test_approve_happy_path(self):
        p = Proj(self)
        p.write(scen("order1", status="proposed"))
        scs, _ = A.load_scenarios(p.d / "tests/accept")
        dig = scs[0].digest()
        r = p.lm("accept", "--approve", dig, "--by", "looks good to me")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(f"approved {dig} order1", r.stdout)
        text = (p.d / "tests/accept/t.accept").read_text()
        self.assertIn("(status approved)", text)
        self.assertNotIn("(status proposed)", text)
        lock_text = (p.d / "accept.lock").read_text()
        self.assertIn(f"{dig} order1\t# approved ", lock_text)
        self.assertIn('by owner: "looks good to me"', lock_text)
        self.assertEqual(p.lm("accept", "--guard").returncode, 0)
        r2 = p.lm("accept", "--approve", dig, "--by", "second time")
        self.assertEqual(r2.returncode, 0)
        self.assertIn("already approved and locked: order1", r2.stdout)
        self.assertEqual((p.d / "accept.lock").read_text(), lock_text)

    def test_approve_unknown_digest_refused_no_change(self):
        p = Proj(self)
        p.write(scen("order1", status="proposed"))
        orig_accept = (p.d / "tests/accept/t.accept").read_text()
        r = p.lm("accept", "--approve", "0000000000000000", "--by", "ok")
        self.assertEqual(r.returncode, 1)
        self.assertIn("unknown scenario digest", r.stderr)
        self.assertEqual((p.d / "tests/accept/t.accept").read_text(), orig_accept)
        self.assertFalse((p.d / "accept.lock").exists())

    def test_approve_empty_by_refused(self):
        p = Proj(self)
        p.write(scen("order1", status="proposed"))
        scs, _ = A.load_scenarios(p.d / "tests/accept")
        dig = scs[0].digest()
        orig_accept = (p.d / "tests/accept/t.accept").read_text()
        r = p.lm("accept", "--approve", dig, "--by", "")
        self.assertEqual(r.returncode, 1)
        self.assertIn("--by text cannot be empty", r.stderr)
        self.assertEqual((p.d / "tests/accept/t.accept").read_text(), orig_accept)
        r2 = p.lm("accept", "--approve", dig)
        self.assertEqual(r2.returncode, 1)
        self.assertIn('--by "TEXT"', r2.stderr)

    def test_approve_stale_digest_refused(self):
        p = Proj(self)
        p.write(scen("order1", status="proposed", expect="(expect 100)"))
        scs, _ = A.load_scenarios(p.d / "tests/accept")
        old_dig = scs[0].digest()
        p.write(scen("order1", status="proposed", expect="(expect 200)"))
        r = p.lm("accept", "--approve", old_dig, "--by", "approved")
        self.assertEqual(r.returncode, 1)
        self.assertIn("unknown scenario digest", r.stderr)
        text = (p.d / "tests/accept/t.accept").read_text()
        self.assertIn("(status proposed)", text)
        self.assertNotIn("(status approved)", text)

    def test_approve_other_scenarios_and_lock_lines_untouched(self):
        p = Proj(self)
        content = (
            '(scenarios\n'
            '  (scenario "s1"\n'
            '    (status approved)\n'
            '    (why "because 1")\n'
            '    (run billing.total (list 100) "MX")\n'
            '    (expect 116))\n'
            '\n'
            '  (scenario "s2"\n'
            '    (status proposed)\n'
            '    (why "because 2")\n'
            '    (run billing.total (list 200) "MX")\n'
            '    (expect 232))\n'
            '\n'
            '  (scenario "s3"\n'
            '    (status proposed)\n'
            '    (why "because 3")\n'
            '    (run billing.total (list 300) "MX")\n'
            '    (expect 348)))\n'
        )
        (p.d / "tests/accept/t.accept").write_text(content)
        scs, _ = A.load_scenarios(p.d / "tests/accept")
        by_name = {s.name: s for s in scs}
        s1_dig = by_name["s1"].digest()
        s2_dig = by_name["s2"].digest()
        (p.d / "accept.lock").write_text(f'{s1_dig} s1\t# approved 2026-01-01 by owner: "initial s1"\n')

        r = p.lm("accept", "--approve", s2_dig, "--by", "only s2")
        self.assertEqual(r.returncode, 0, r.stderr)

        new_content = (p.d / "tests/accept/t.accept").read_text()
        expected_content = content.replace('(status proposed)\n    (why "because 2")', '(status approved)\n    (why "because 2")')
        self.assertEqual(new_content, expected_content)

        lock_lines = (p.d / "accept.lock").read_text().splitlines()
        self.assertEqual(len(lock_lines), 2)
        lock_map = {l.partition(" ")[2].partition("\t#")[0]: l for l in lock_lines}
        self.assertEqual(lock_map["s1"], f'{s1_dig} s1\t# approved 2026-01-01 by owner: "initial s1"')
        self.assertTrue(lock_map["s2"].startswith(f'{s2_dig} s2\t# approved '))
        self.assertIn('by owner: "only s2"', lock_map["s2"])

    def test_guard_ok_after_approve(self):
        p = Proj(self)
        p.write(scen("ok", status="proposed"))
        scs, _ = A.load_scenarios(p.d / "tests/accept")
        dig = scs[0].digest()
        p.lm("accept", "--approve", dig, "--by", "all good")
        r = p.lm("accept", "--guard")
        self.assertEqual(r.returncode, 0)
        self.assertIn("guard: OK", r.stderr)
        r2 = p.lm("accept")
        self.assertEqual(r2.returncode, 0)
        self.assertIn("PASS  approved  ok", r2.stdout)

    def test_legacy_lock_lines_still_pass_guard(self):
        p = Proj(self)
        p.write(scen("legacy1"), scen("legacy2"))
        scs, _ = A.load_scenarios(p.d / "tests/accept")
        by_n = {s.name: s for s in scs}
        (p.d / "accept.lock").write_text(
            f"{by_n['legacy1'].digest()} legacy1\n"
            f"{by_n['legacy2'].digest()} legacy2\n"
        )
        r = p.lm("accept", "--guard")
        self.assertEqual(r.returncode, 0)
        self.assertIn("guard: OK", r.stderr)

    def test_bless_preserves_suffixes_of_unchanged_entries(self):
        p = Proj(self)
        p.write(scen("s1"), scen("s2"))
        scs, _ = A.load_scenarios(p.d / "tests/accept")
        by_n = {s.name: s for s in scs}
        s1_dig, s2_dig = by_n["s1"].digest(), by_n["s2"].digest()
        (p.d / "accept.lock").write_text(
            f'{s1_dig} s1\t# approved 2026-05-01 by owner: "s1 note"\n'
        )
        A.write_lock(p.d / "accept.lock", scs)
        lock_lines = (p.d / "accept.lock").read_text().splitlines()
        lock_map = {l.partition(" ")[2].partition("\t#")[0]: l for l in lock_lines}
        self.assertEqual(lock_map["s1"], f'{s1_dig} s1\t# approved 2026-05-01 by owner: "s1 note"')
        self.assertEqual(lock_map["s2"], f'{s2_dig} s2')

    def test_approve_custom_dir_and_lock(self):
        p = Proj(self)
        custom_dir = p.d / "custom_accept"
        custom_dir.mkdir()
        (custom_dir / "custom.accept").write_text('(scenarios ' + scen("custom_scen", status="proposed") + ')')
        scs, _ = A.load_scenarios(custom_dir)
        dig = scs[0].digest()
        custom_lock = p.d / "custom.lock"
        r = p.lm("accept", "--dir", str(custom_dir), "--lock", str(custom_lock), "--approve", dig, "--by", "custom ok")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(custom_lock.exists())
        self.assertIn("custom_scen", custom_lock.read_text())
        self.assertIn("(status approved)", (custom_dir / "custom.accept").read_text())

    def test_retire_removes_only_a_vanished_scenario(self):
        p = Proj(self)
        p.write(scen("old", status="proposed") + scen("keep", status="proposed", expect="(expect 348)", run='(run billing.total (list 100 200 0) "MX")'))
        scs, _ = A.load_scenarios(p.d / "tests/accept")
        self.assertEqual(p.lm("accept", "--approve", *[s.digest() for s in scs], "--by", "yes").returncode, 0)
        p.write(scen("keep", status="approved", run='(run billing.total (list 100 200 0) "MX")'))
        self.assertIn("MISSING   old", p.lm("accept", "--guard").stdout)
        r = p.lm("accept", "--retire", "keep", "--by", "drop it")
        self.assertEqual(r.returncode, 1)
        self.assertIn("still exists", r.stderr)
        self.assertEqual(p.lm("accept", "--retire", "old").returncode, 1)
        self.assertIn("not in the lock", p.lm("accept", "--retire", "nope", "--by", "x").stderr)
        before = (p.d / "accept.lock").read_text()
        r = p.lm("accept", "--retire", "old", "--by", "retire the old one")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(" old", r.stdout)
        after = (p.d / "accept.lock").read_text()
        self.assertNotIn(" old", after)
        self.assertEqual(after, "".join(l + "\n" for l in before.splitlines() if " old" not in l))
        self.assertEqual(p.lm("accept", "--guard").returncode, 0)

    def test_repo_scenarios_are_clean(self):
        r = subprocess.run([sys.executable, "-m", "lm", "accept"], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertNotIn("BAD", r.stdout)
        self.assertNotIn("FAIL ", r.stdout)


class TestExplain(unittest.TestCase):
    def test_goldens(self):
        for name, sym in (("explain-billing-total", "billing.total"), ("explain-shapes-scale", "shapes.scale"), ("explain-io-print", "io.print")):
            p = golden_command(["explain", sym, "examples", "stdlib"])
            self.assertEqual(p.returncode, 0, p.stderr)
            f = GOLDEN / f"{name}.txt"
            if os.environ.get("UPDATE_GOLDEN"):
                f.write_text(p.stdout)
            self.assertEqual(p.stdout, f.read_text(), name)

    def test_errors(self):
        for args in (["explain"], ["explain", "nodot"], ["explain", "billing.nope"], ["explain", "billing.BadRegion"]):
            p = subprocess.run([sys.executable, "-m", "lm", *args], cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(p.returncode, 3, args)


if __name__ == "__main__":
    unittest.main()
