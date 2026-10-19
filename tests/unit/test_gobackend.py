"""Go backend (M8(c)/(d)): differential test against the interpreter, built-binary fixtures, CLI.

Tests that need the Go toolchain SKIP with a visible message when `go` is not found (never pass).
"""
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from lm import gobackend, ir
from lm.build import find_go, missing_prims, run_examples_go, runtime_prims
from lm.check import Checker
from lm.interp import Interp
from lm.loader import load
from lm.prelude import EFFECTS
from lm.prims import PRIMS
from lm.runner import example_outcomes, in_big_stack, runtime_diag
from lm.values import LmFail, Named, show

ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / "tests/spec/build"
DIFF_DIRS = ["stdlib", "examples", "tests/spec/run", "tests/spec/build", "bench/tasks"]


def lm(*args, env=None):
    e = {**os.environ, "PYTHONPATH": str(ROOT), **(env or {})}
    p = subprocess.run([sys.executable, "-m", "lm", *args], cwd=ROOT, capture_output=True, text=True, env=e)
    return p.returncode, p.stdout, p.stderr


def need_go():
    if find_go() is None:
        sys.stderr.write("\nSKIP: Go toolchain not found (PATH or LM_GO); compiled differential tests NOT run\n")
        raise unittest.SkipTest("go not found: compiled tests not run")


def interp_entry(path, contracts, args=(), stdin=""):
    """Run MOD.main under the interpreter like a binary: (exit, stdout, stderr text, fault code)."""
    prog = load([str(path)])
    Checker(prog).run()
    f = prog.modules[path.stem].fns["main"]
    out, err = io.StringIO(), io.StringIO()
    it = Interp(prog, allowed=EFFECTS, contracts=contracts, out=out, err=err, args=args,
                stdin=io.BytesIO(stdin.encode("utf-8")))

    def go():
        try:
            return "ok", it.apply(Named(f), [])
        except LmFail as x:
            return "fail", f"(fail {x.id}" + "".join(" " + show(a) for a in x.args_) + ")\n"
        except Exception as ex:
            d = runtime_diag(ex, it=it)
            if d is None:
                raise
            return "fault", d.code

    kind, v = in_big_stack(go)
    code = {"ok": v if isinstance(v, int) and not isinstance(v, bool) else 0, "fail": 1, "fault": 70}[kind]
    return code, out.getvalue(), err.getvalue() + (v if kind == "fail" else ""), v if kind == "fault" else None


class Differential(unittest.TestCase):
    def test_every_example_identical_interpreted_and_compiled(self):
        need_go()
        prog = load(DIFF_DIRS)
        Checker(prog).run()
        self.assertEqual([d.to_json() for d in prog.diags if d.severity == "error"], [])
        want = example_outcomes(prog, prog.targets)
        got = run_examples_go(prog, prog.targets)
        self.assertEqual(want["tailcall/loop/example#0"], ("ok", "(Some 1000000)"))
        self.assertIn("tailcall/loop/example#0", got)
        self.assertEqual(want["json-runtime/decode/example#0"], ("ok", "json.JNull"))
        self.assertIn("json-runtime/decode/example#0", got)
        self.assertGreaterEqual(len(want), 369)
        diffs = [f"{k}: interp {want.get(k)} != go {got.get(k)}" for k in sorted(set(want) | set(got)) if want.get(k) != got.get(k)]
        self.assertEqual(diffs, [])
        kinds = {k for k, _ in want.values()}
        self.assertEqual(kinds, {"ok", "fail", "fault"})  # failures and faults are compared too
        sys.stderr.write(f"\ndifferential: {len(want)} examples identical interpreted and compiled\n")


class BuiltBinaries(unittest.TestCase):
    def test_fixtures(self):
        need_go()
        n = 0
        with tempfile.TemporaryDirectory() as tmp:
            for src in sorted(BUILD.glob("*.lm")):
                for k, run in enumerate(json.loads(src.with_suffix(".expect").read_text())):
                    exe = Path(tmp) / f"{src.stem}-{k}"
                    rc, out, err = lm("build", f"{src.stem}.main", str(src.relative_to(ROOT)), "-o", str(exe), *run.get("flags", []))
                    self.assertEqual((rc, out), (0, ""), f"{src.name}: {err}")
                    args = [a.replace("$TMP", tmp) for a in run.get("args", [])]
                    p = subprocess.run([str(exe), *args], input=run.get("stdin", "").encode(), capture_output=True)
                    pout, perr = p.stdout.decode(), p.stderr.decode()
                    where = f"{src.name} run {k}"
                    self.assertEqual((p.returncode, pout), (run["exit"], run["stdout"]), where)
                    if "code" in run:
                        diag = json.loads(perr)
                        for key in ("code", "path", "found"):
                            if key in run:
                                self.assertEqual(diag[key], run[key], where)
                    else:
                        self.assertEqual(perr, run.get("stderr", ""), where)
                    if run.get("interp", True):
                        code, iout, ierr, fcode = interp_entry(src, "--no-contracts" not in run.get("flags", []), args, run.get("stdin", ""))
                        self.assertEqual((code, iout), (p.returncode, pout), where + " (interpreter)")
                        self.assertEqual(fcode if "code" in run else ierr, run.get("code", run.get("stderr", "")), where + " (interpreter)")
                    n += 1
        self.assertGreaterEqual(n, 20)

    def test_cross_builds(self):
        need_go()
        magic = {("darwin", "arm64"): b"\xcf\xfa\xed\xfe", ("darwin", "amd64"): b"\xcf\xfa\xed\xfe", ("linux", "arm64"): b"\x7fELF"}
        with tempfile.TemporaryDirectory() as tmp:
            for (os_, arch), m in magic.items():
                exe = Path(tmp) / f"hello-{os_}-{arch}"
                rc, _, err = lm("build", "hello.main", "tests/spec/build/hello.lm", "-o", str(exe), "--os", os_, "--arch", arch)
                self.assertEqual(rc, 0, err)
                self.assertEqual(exe.read_bytes()[:4], m, f"{os_}/{arch}")

    def test_keep_go_writes_sources(self):
        need_go()
        with tempfile.TemporaryDirectory() as tmp:
            rc, _, err = lm("build", "status.main", "tests/spec/build/status.lm", "-o", f"{tmp}/s", "--keep-go", f"{tmp}/src")
            self.assertEqual(rc, 0, err)
            self.assertTrue((Path(tmp) / "src/main.go").is_file() and (Path(tmp) / "src/go.mod").is_file())


class Cli(unittest.TestCase):
    def test_go_missing_is_usage_error(self):
        rc, _, err = lm("build", "hello.main", "tests/spec/build/hello.lm", env={"PATH": "/nonexistent", "LM_GO": "/nonexistent/go"})
        self.assertEqual(rc, 3)
        self.assertIn("Go toolchain", err)

    def test_usage_errors(self):
        if find_go() is None:
            self.skipTest("go not found")
        self.assertEqual(lm("build", "list.sum")[0], 3)  # entry takes parameters
        self.assertEqual(lm("build", "hello.main", "tests/spec/build/hello.lm", "--os", "windows")[0], 3)
        self.assertEqual(lm("build", "hello.nope", "tests/spec/build/hello.lm")[0], 3)
        self.assertEqual(lm("build")[0], 3)


class Runtime(unittest.TestCase):
    def test_every_python_prim_has_a_go_twin(self):
        have = runtime_prims()
        self.assertEqual(sorted(p for p in PRIMS if gobackend.prim_name(p) not in have), [])

    def test_missing_prim_is_reported(self):
        self.assertEqual(missing_prims(ir.Program(prims={"str.nope"})), ["str.nope"])

    def test_mangling_is_injective_on_lm_names(self):
        self.assertNotEqual(gobackend.mangle("a-b.c", "F_"), gobackend.mangle("a.b-c", "F_"))
        self.assertEqual(gobackend.mangle("list.index-of", "F_"), "F_list_X_index_of")
