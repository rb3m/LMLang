"""ADR-075 vectors, shared by the interpreter and both standalone targets."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

from lm.build import find_go, run_examples_go, run_examples_py
from lm.check import Checker
from lm.loader import load
from lm.runtime_cases import fixture_outcomes
from lm.sexpr import Atom
from lm.printer import flat

ROOT = Path(__file__).resolve().parents[2]
VECTORS = ROOT / "tests/spec/pat/vectors.json"


def quoted(value):
    return flat(Atom("str", value))


def lm_value(value):
    if value is None:
        return "None"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return quoted(value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, list):
        return "(list" + "".join(" " + lm_value(x) for x in value) + ")"
    fields = []
    for key in ("start", "end", "text", "groups"):
        item = value[key]
        if key == "groups":
            item = "(list" + "".join(
                " None" if x is None else " (Some " + quoted(x) + ")"
                for x in item) + ")"
        else:
            item = lm_value(item)
        fields.append(f" ({key} {item})")
    return "(new pat.Match" + "".join(fields) + ")"


def harness(directory):
    forms, cases = [], {}
    for index, case in enumerate(json.loads(VECTORS.read_text())):
        name = f"v{index}"
        pattern, text = quoted(case["pattern"]), quoted(case["text"])
        op, expected = case["op"], case["expected"]
        if op == "compile-error":
            ret = "(Pair Int Str)"
            body = (f"(let ((source {pattern})) "
                    "(try (let ((compiled (pat.compile source))) "
                    "(pair -1 \"ok\")) "
                    "(catch pat.BadPattern (pos reason) (pair pos reason))))")
            want = f'(pair {expected["pos"]} {quoted(expected["reason"])})'
        else:
            ret = {"matches": "Bool", "find": "(Opt pat.Match)",
                   "find-all": "(List pat.Match)", "split": "(List Str)",
                   "replace-all": "Str", "replace-with": "Str",
                   "print": "pat.Pat"}[op]
            suffix = ""
            if op == "replace-all":
                suffix = " " + quoted(case["replacement"])
            if op == "replace-with":
                suffix = (' (lam ((m pat.Match)) '
                          '(str.concat "[" (str.concat (get m text) "]")))')
            body = f"(pat.{op} {text} (pat.compile {pattern}){suffix})"
            if op == "print":
                body = f"(pat.compile {pattern})"
            want = expected if op == "print" else lm_value(expected)
            if op == "find" and expected is not None:
                want = f"(Some {want})"
        forms.append(
            f'  (fn {name}\n    (purpose "Shared pattern vector {index}.")\n'
            f'    (sig -> {ret})\n    (body {body}))')
        cases[name] = {"expected": want}
    path = directory / "patvectors.lm"
    path.write_text('(module patvectors\n  (purpose "Pattern conformance.")\n'
                    '  (use pat str)\n' + '\n'.join(forms) + ')\n')
    path.with_suffix(".cases.json").write_text(json.dumps(cases))
    prog = load([str(path)])
    Checker(prog).run()
    return prog, {f"patvectors/{k}/case": ("ok", v["expected"])
                  for k, v in cases.items()}


class PatternConformance(unittest.TestCase):
    def test_shared_vectors_all_runtimes(self):
        with tempfile.TemporaryDirectory(prefix="lm-pat-vectors-") as tmp:
            prog, want = harness(Path(tmp))
            errors = [d.to_json() for d in prog.diags if d.severity == "error"]
            self.assertEqual(errors, [])
            self.assertEqual(fixture_outcomes(prog, prog.targets), want)
            self.assertEqual(run_examples_py(prog, prog.targets), want)
            if find_go() is None:
                sys.stderr.write(
                    "\nSKIP: Go not found; pat Go conformance omitted\n")
                return
            self.assertEqual(run_examples_go(prog, prog.targets), want)

    def test_nullable_loop_is_not_backtracking(self):
        # A process timeout makes a mistaken backtracking VM fail promptly.
        script = ('from lm.pat_compile import compile_pattern\n'
                  'from lm.pat_vm import search\n'
                  'p = compile_pattern("(a*)*b")\n'
                  'assert search(p, "a" * 5000) is None\n')
        started = time.monotonic()
        result = subprocess.run([sys.executable, "-c", script], cwd=ROOT,
                                capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertLess(time.monotonic() - started, 5)
