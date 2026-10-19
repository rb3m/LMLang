"""Python backend (ADR-062 Piece 1): core language, differential tests, built-binary fixtures, CLI."""
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from lm import gobackend, ir, pybackend
from lm.build import find_go, lower_examples, run_examples_go
from lm.check import Checker
from lm.interp import Interp
from lm.loader import load
from lm.lower import lower
from lm.prelude import EFFECTS
from lm.pybackend import BuildError, check_features, emit_cases
from lm.runner import example_outcomes, in_big_stack, runtime_diag
from lm.values import LmFail, Named, show

ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / "tests/spec/build"
DIFF_DIRS = ["stdlib", "examples", "tests/spec/run", "tests/spec/build", "bench/tasks"]


def lm(*args, env=None, cwd=ROOT):
    e = {**os.environ, "PYTHONPATH": str(ROOT), **(env or {})}
    p = subprocess.run([sys.executable, "-m", "lm", *args], cwd=cwd, capture_output=True, text=True, env=e)
    return p.returncode, p.stdout, p.stderr


def interp_entry(path, contracts, args=(), stdin=""):
    """Run MOD.main under interpreter like a binary: (exit, stdout, stderr text, fault code)."""
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


class PyDifferential(unittest.TestCase):
    def test_examples_identical_interpreted_and_python(self):
        prog = load(DIFF_DIRS)
        Checker(prog).run()
        self.assertEqual([d.to_json() for d in prog.diags if d.severity == "error"], [])
        want = example_outcomes(prog, prog.targets)
        irp_all, cases = lower_examples(prog, prog.targets)

        # In Piece 2, all cases are supported on Python target (0 refused)
        check_features(irp_all)
        src = emit_cases(irp_all, cases)
        with tempfile.TemporaryDirectory(prefix="lm-pycases-") as tmp:
            script = Path(tmp) / "cases.py"
            script.write_text(src, encoding="utf-8")
            script.chmod(script.stat().st_mode | 0o755)
            p = subprocess.run([sys.executable, str(script)], cwd=tmp, capture_output=True, text=True)
            self.assertEqual(p.returncode, 0, f"case harness crashed:\n{p.stderr}")
            got_py = {}
            for line in p.stdout.splitlines():
                label, kind, detail = line.split("\t", 2)
                got_py[label] = (kind, detail)

        # Includes the offline HTTP invalid-request runtime case.
        self.assertEqual(len(cases), 879)
        diffs = [f"{k}: interp {want.get(k)} != py {got_py.get(k)}"
                 for k, _, _ in cases if want.get(k) != got_py.get(k)]
        self.assertEqual(diffs, [])

        # If Go toolchain is available, verify three-way parity across all cases
        if find_go() is not None:
            got_go = run_examples_go(prog, prog.targets)
            go_diffs = [f"{k}: py {got_py.get(k)} != go {got_go.get(k)}"
                        for k, _, _ in cases if got_py.get(k) != got_go.get(k)]
            self.assertEqual(go_diffs, [])

        sys.stderr.write(f"\n[Python Target] differential: {len(cases)} cases ran, 0 refused\n")


class PyBuiltBinaries(unittest.TestCase):
    def test_fixtures(self):
        ran_cases = 0
        refused_fixtures = 0
        with tempfile.TemporaryDirectory(prefix="lm-pybuild-") as tmp:
            for src in sorted(BUILD.glob("*.lm")):
                runs = json.loads(src.with_suffix(".expect").read_text())
                probe_exe = Path(tmp) / f"probe-{src.stem}.py"
                rc_probe, _, err_probe = lm("build", "--target", "py", f"{src.stem}.main",
                                            str(src.relative_to(ROOT)), "-o", str(probe_exe))
                self.assertEqual(rc_probe, 0, f"{src.name} probe failed: {err_probe}")

                for k, run in enumerate(runs):
                    exe = Path(tmp) / f"{src.stem}-{k}.py"
                    flags = run.get("flags", [])
                    rc, out, err = lm("build", "--target", "py", f"{src.stem}.main",
                                      str(src.relative_to(ROOT)), "-o", str(exe), *flags)
                    self.assertEqual((rc, out), (0, ""), f"{src.name}: {err}")
                    self.assertTrue(exe.is_file())
                    self.assertTrue(os.access(exe, os.X_OK))

                    args = [a.replace("$TMP", tmp) for a in run.get("args", [])]
                    # Run executable from outside the repo (in tmp dir)
                    p = subprocess.run([str(exe), *args], input=run.get("stdin", ""),
                                       cwd=tmp, capture_output=True, text=True)
                    pout, perr = p.stdout, p.stderr
                    where = f"{src.name} run {k}"
                    self.assertEqual((p.returncode, pout), (run["exit"], run["stdout"]), where)
                    if "code" in run:
                        diag = json.loads(perr)
                        # Byte-level format must match lm/diag.py and Go: field order, compact separators.
                        order = ["code", "severity", "file", "line", "col", "path", "msg", "expected", "found", "fix", "data"]
                        self.assertEqual(list(diag), [k for k in order if k in diag], where)
                        self.assertEqual(perr.strip(), json.dumps(diag, ensure_ascii=False, separators=(",", ":")), where)
                        for key in ("code", "path", "found"):
                            if key in run:
                                self.assertEqual(diag[key], run[key], where)
                    else:
                        self.assertEqual(perr, run.get("stderr", ""), where)

                    # Compare with interpreter if eligible for interp
                    if run.get("interp", True):
                        code, iout, ierr, fcode = interp_entry(src, "--no-contracts" not in flags,
                                                               args, run.get("stdin", ""))
                        self.assertEqual((code, iout), (p.returncode, pout), where + " (interp)")
                        self.assertEqual(fcode if "code" in run else ierr,
                                         run.get("code", run.get("stderr", "")), where + " (interp)")

                    # Compare with Go if available
                    if find_go() is not None:
                        go_exe = Path(tmp) / f"go-{src.stem}-{k}"
                        grc, _, gerr = lm("build", f"{src.stem}.main", str(src.relative_to(ROOT)),
                                          "-o", str(go_exe), *flags)
                        if grc == 0:
                            gp = subprocess.run([str(go_exe), *args], input=run.get("stdin", ""),
                                                cwd=tmp, capture_output=True, text=True)
                            self.assertEqual((p.returncode, pout), (gp.returncode, gp.stdout), where + " (go)")
                            if "code" in run:
                                gdiag = json.loads(gp.stderr)
                                self.assertEqual(diag["code"], gdiag["code"], where + " (go code)")

                    ran_cases += 1

        self.assertEqual(refused_fixtures, 0)
        self.assertEqual(ran_cases, 42)
        sys.stderr.write(f"\n[Python Target] fixtures: {ran_cases} test runs passed, "
                         f"{refused_fixtures} fixtures refused\n")


class PyCli(unittest.TestCase):
    def test_default_output_and_executable_bit(self):
        with tempfile.TemporaryDirectory(prefix="lm-cli-") as tmp:
            rc, out, err = lm("build", "--target", "py", "hello.main", str(BUILD / "hello.lm"), cwd=tmp)
            self.assertEqual(rc, 0, err)
            default_file = Path(tmp) / "main.py"
            self.assertTrue(default_file.is_file())
            self.assertTrue(os.access(default_file, os.X_OK))
            first_line = default_file.read_text(encoding="utf-8").splitlines()[0]
            self.assertEqual(first_line, "#!/usr/bin/env python3")

    def test_os_arch_with_target_py_is_usage_error(self):
        rc, _, err = lm("build", "--target", "py", "--os", "linux", "hello.main", "tests/spec/build/hello.lm")
        self.assertEqual(rc, 3)
        self.assertIn("--os/--arch cannot be used with --target py", err)

        rc, _, err = lm("build", "--target", "py", "--arch", "arm64", "hello.main", "tests/spec/build/hello.lm")
        self.assertEqual(rc, 3)
        self.assertIn("--os/--arch cannot be used with --target py", err)

    def test_keep_go_with_target_py_is_usage_error(self):
        rc, _, err = lm("build", "--target", "py", "--keep-go", "/tmp/foo", "hello.main", "tests/spec/build/hello.lm")
        self.assertEqual(rc, 3)
        self.assertIn("--keep-go cannot be used with --target py", err)

    def test_invalid_target_is_usage_error(self):
        rc, _, err = lm("build", "--target", "wasm", "hello.main", "tests/spec/build/hello.lm")
        self.assertEqual(rc, 3)
        self.assertIn("--target must be one of go, py", err)

    def test_embedding_reaches_only_used_features(self):
        with tempfile.TemporaryDirectory(prefix="lm-reach-") as tmp:
            # 1. Program without Map/Set or Floats: hello.lm
            hello_py = Path(tmp) / "hello.py"
            rc, _, err = lm("build", "--target", "py", "hello.main", "tests/spec/build/hello.lm", "-o", str(hello_py))
            self.assertEqual(rc, 0, err)
            hello_src = hello_py.read_text(encoding="utf-8")
            self.assertNotIn("class Coll", hello_src)
            self.assertNotIn("INV_LN2", hello_src)
            self.assertNotIn("rem_pio2", hello_src)
            self.assertNotIn("SplitMix64", hello_src)
            self.assertNotIn("prim_json_parse", hello_src)
            self.assertNotIn("prim_fs_read", hello_src)
            self.assertNotIn("prim_time_now_ms", hello_src)

            # 2. Program with Map/Set: bin-maps.lm
            maps_py = Path(tmp) / "maps.py"
            rc, _, err = lm("build", "--target", "py", "bin-maps.main", "tests/spec/build/bin-maps.lm", "-o", str(maps_py))
            self.assertEqual(rc, 0, err)
            maps_src = maps_py.read_text(encoding="utf-8")
            self.assertIn("class Coll", maps_src)
            self.assertNotIn("INV_LN2", maps_src)
            self.assertNotIn("rem_pio2", maps_src)

            # 3. Program with float transcendental math: float.exp
            flt_lm = Path(tmp) / "flt.lm"
            flt_lm.write_text(
                '(module flt\n'
                '  (purpose "Float demo.")\n'
                '  (use float io str)\n'
                '  (fn main\n'
                '    (purpose "Entry.")\n'
                '    (sig -> Unit)\n'
                '    (eff io.out)\n'
                '    (body\n'
                '      (let ((a (io.print (str.from-float (float.exp 1.0)))))\n'
                '        unit))))\n',
                encoding="utf-8",
            )
            lm("fmt", str(flt_lm))
            flt_py = Path(tmp) / "flt.py"
            rc, _, err = lm("build", "--target", "py", "flt.main", str(flt_lm), "-o", str(flt_py))
            self.assertEqual(rc, 0, err)
            flt_src = flt_py.read_text(encoding="utf-8")
            self.assertIn("INV_LN2", flt_src)
            self.assertNotIn("class Coll", flt_src)

    def test_seeded_rand_parity_outside_repo(self):
        with tempfile.TemporaryDirectory(prefix="lm-rand-outside-") as tmp:
            src_dir = Path(tmp) / "src"
            src_dir.mkdir()
            rand_lm = src_dir / "randdemo.lm"
            rand_lm.write_text(
                '(module randdemo\n'
                '  (purpose "Random stream demo.")\n'
                '  (use io rand str)\n'
                '  (fn main\n'
                '    (purpose "Entry.")\n'
                '    (sig -> Unit)\n'
                '    (eff io.out rand)\n'
                '    (body\n'
                '      (let ((a (io.print (str.from-int (rand.int 0 1000000))))\n'
                '            (b (io.print (str.from-int (rand.int 0 1000000))))\n'
                '            (c (io.print (str.from-int (rand.int 0 1000000)))))\n'
                '        unit))))\n',
                encoding="utf-8",
            )
            lm("fmt", str(rand_lm))

            # 1. Interpreter: lm run --seed 12345 --allow io.out --allow rand randdemo.main
            rc_interp, out_interp, err_interp = lm(
                "run", "--seed", "12345", "--allow", "io.out", "--allow", "rand", "randdemo.main",
                cwd=tmp,
            )
            self.assertEqual(rc_interp, 0, err_interp)
            self.assertTrue(out_interp.endswith("unit\n"))
            expected_output = out_interp.removesuffix("unit\n")

            # 2. Python target: built binary under LM_SEED=12345
            py_bin = Path(tmp) / "randdemo.py"
            rc, out, err = lm("build", "--target", "py", "randdemo.main", str(rand_lm), "-o", str(py_bin), cwd=tmp)
            self.assertEqual(rc, 0, err)
            p_py = subprocess.run([sys.executable, str(py_bin)], cwd=tmp, env={**os.environ, "LM_SEED": "12345"},
                                  capture_output=True, text=True)
            self.assertEqual(p_py.returncode, 0, p_py.stderr)
            self.assertEqual(p_py.stdout, expected_output)

            # Invalid LM_SEED should exit 3 with usage error message
            p_py_bad = subprocess.run([sys.executable, str(py_bin)], cwd=tmp, env={**os.environ, "LM_SEED": "xyz"},
                                      capture_output=True, text=True)
            self.assertEqual(p_py_bad.returncode, 3)
            self.assertEqual(p_py_bad.stderr, "LM_SEED must be a signed 64-bit decimal integer\n")

            # 3. Go target: built binary under LM_SEED=12345 (if Go available)
            if find_go() is not None:
                go_bin = Path(tmp) / "randdemo_go"
                rc_go, out_go, err_go = lm("build", "randdemo.main", str(rand_lm), "-o", str(go_bin), cwd=tmp)
                self.assertEqual(rc_go, 0, err_go)
                p_go = subprocess.run([str(go_bin)], cwd=tmp, env={**os.environ, "LM_SEED": "12345"},
                                      capture_output=True, text=True)
                self.assertEqual(p_go.returncode, 0, p_go.stderr)
                self.assertEqual(p_go.stdout, expected_output)

