"""`lm bench`: measures the PRD success metrics S1-S6 (PRD.md; history in docs/archive/milestones-M0-M12.md M6). Output: bench/results/{summary.md,results.json}."""
from __future__ import annotations

import ast
import contextlib
import importlib.util
import io
import json
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
from pathlib import Path

from .check import Checker
from .index import Index, tokens
from .interp import Interp
from .loader import load
from .printer import flat, print_module
from .runner import in_big_stack
from .sexpr import read
from .values import LmFail, Named, Rec, Var, show

ROOT = Path(__file__).resolve().parents[1]
TASKS = ROOT / "bench" / "tasks"


def task_dirs(base=TASKS):
    return sorted(d for d in Path(base).iterdir() if d.is_dir())


def lm_file(d):
    return next(d.glob("*.lm"))


def py_file(d):
    return next(d.glob("*.py"))


def to_lm(v):
    """JSON case value -> LM source text."""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, str):
        return json.dumps(v)
    if v is None:
        return "unit"
    if isinstance(v, list):
        return "(list" + "".join(" " + to_lm(x) for x in v) + ")"
    if "$new" in v:
        return f"(new {v['$new']}" + "".join(f" ({k} {to_lm(x)})" for k, x in v.items() if k != "$new") + ")"
    a = v["args"]
    return f"({v['$v']}" + "".join(" " + to_lm(x) for x in a) + ")" if a else v["$v"]


def from_lm(v):
    """LM runtime value -> JSON-comparable value."""
    if isinstance(v, (bool, int, str)):
        return v
    if isinstance(v, tuple):
        return [from_lm(x) for x in v]
    if isinstance(v, Rec):
        return {k: from_lm(x) for k, x in v.items}
    if isinstance(v, Var):
        return {"$v": v.name, "args": [from_lm(a) for a in v.args]}
    return None  # unit


def run_lm_case(prog, mod, case):
    m = prog.modules[mod]
    f = m.fns[case["fn"]]
    buf = io.StringIO()
    it = Interp(prog, allowed=["io.out"], contracts=True, out=buf)
    nodes = []
    for a in case["args"]:
        n, d = read(to_lm(a), "<case>")
        assert n is not None, (case, d)
        nodes.append(n)

    def go():
        try:
            return "ok", it.apply(Named(f), [it.ev(n, {}, m) for n in nodes])
        except LmFail as x:
            return "fail", x.id.split(".")[-1]
    kind, val = in_big_stack(go)
    return kind, (from_lm(val) if kind == "ok" else val), buf.getvalue()


def load_py(path):
    spec = importlib.util.spec_from_file_location("bench_" + path.stem, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _plain(v):
    """JSON case value as Python sees it: records are plain dicts."""
    if isinstance(v, list):
        return [_plain(x) for x in v]
    if isinstance(v, dict) and "$new" in v:
        return {k: _plain(x) for k, x in v.items() if k != "$new"}
    return v


def run_py_case(mod, case):
    name = case["fn"].replace("-", "_")
    fn = getattr(mod, name, None) or getattr(mod, name + "_value", None) or getattr(mod, name + "_account", None)
    args = [_plain(a) for a in case.get("py_args", case["args"])]
    out = io.StringIO()
    try:
        with contextlib.redirect_stdout(out):
            r = fn(*args)
        return "ok", r, out.getvalue()
    except AssertionError:
        raise
    except Exception as ex:
        return "fail", type(ex).__name__, out.getvalue()


def equivalence(dirs):
    """Run each task's cases through LM and Python; report agreement with the declared expectations."""
    rows = []
    for d in dirs:
        prog = load([str(d)])
        Checker(prog).run()
        mod = lm_file(d).stem
        pm = load_py(py_file(d))
        pm._examples()
        cases = json.loads((d / "cases.json").read_text())
        bad = []
        for c in cases:
            want = c["want"]
            lk, lv, lo = run_lm_case(prog, mod, c)
            pk, pv, po = run_py_case(pm, c)
            if isinstance(want, dict) and "fail" in want:
                ok_l, ok_p = (lk, lv) == ("fail", want["fail"]), (pk, pv) == ("fail", want["fail"])
            else:
                ok_l = lk == "ok" and lv == want
                ok_p = pk == "ok" and pv == c.get("py_want", want)
                if "out" in c:
                    ok_l, ok_p = ok_l and lo == c["out"], ok_p and po == c["out"]
            if not (ok_l and ok_p):
                bad.append({"case": c, "lm": [lk, lv, lo], "py": [pk, pv, po]})
        rows.append({"task": d.name, "cases": len(cases), "disagree": bad})
    return rows


# ---- S5 ---------------------------------------------------------------------------------
def bare_python(src):
    """Python without docstrings, assert-based examples and contract asserts (the leanest equivalent)."""
    tree = ast.parse(src)
    tree.body = [n for n in tree.body if not (isinstance(n, ast.FunctionDef) and n.name == "_examples")]

    class Strip(ast.NodeTransformer):
        def visit_FunctionDef(self, n):
            n.body = [s for s in n.body if not isinstance(s, ast.Assert)]
            if n.body and isinstance(n.body[0], ast.Expr) and isinstance(getattr(n.body[0], "value", None), ast.Constant) and isinstance(n.body[0].value.value, str):
                n.body = n.body[1:]
            n.body = n.body or [ast.Pass()]
            self.generic_visit(n)
            return n
    return ast.unparse(Strip().visit(tree))


PY_TOK = re.compile(r"\w+|[^\w\s]")
MERGED_TOK = re.compile(r"\w+|[^\w\s]+")  # sensitivity: runs of punctuation count once, like most BPE vocabularies


def s5(dirs):
    rows = []
    for d in dirs:
        lm = tokens(print_module(load([str(d)]).modules[lm_file(d).stem].root))
        full = len(PY_TOK.findall(py_file(d).read_text()))
        bare = len(PY_TOK.findall(bare_python(py_file(d).read_text())))
        lm_text = print_module(load([str(d)]).modules[lm_file(d).stem].root)
        rows.append({"task": d.name, "lm": lm, "py_full": full, "py_bare": bare,
                     "lm_merged": len(MERGED_TOK.findall(lm_text)), "py_full_merged": len(MERGED_TOK.findall(py_file(d).read_text()))})
    return rows


# ---- S1 / S2 ----------------------------------------------------------------------------
def s1_s2(dirs):
    prog = load([str(d) for d in dirs])
    Checker(prog).run()
    idx = Index(prog)
    whole = sum(tokens(print_module(prog.modules[n].root)) for n in prog.targets)
    s1, s1b, s2, nfns = [], [], [], 0
    for n in prog.targets:
        m = prog.modules[n]
        file_tok = tokens(print_module(m.root))
        for fname in sorted(m.fns):
            nfns += 1
            f = m.fns[fname]
            q = f"{n}.{fname}"
            text, _, _ = idx.slice(q, False, 1, None)
            s1.append(tokens(text) / whole)
            s1b.append(tokens(text) / file_tok)
            body = f.clauses["body"][0].items[1]
            cmd = f"lm edit replace-body {q} '{flat(body)}'"
            s2.append(tokens(cmd) / file_tok)
    return {"functions": nfns, "whole_tokens": whole, "s1_median": statistics.median(s1), "s1_max": max(s1), "s1_module_median": statistics.median(s1b), "s1_module_max": max(s1b),
            "s2_median": statistics.median(s2), "s2_max": max(s2)}


# ---- S3 ---------------------------------------------------------------------------------
# (id, category, task, [(old, new)...], replace_all)
H = [
    ("cart", "unknown-fn", "01-cart", "list.sum", "list.total"),
    ("cart", "unknown-fn", "01-cart", "list.map", "list.mapi"),
    ("fizz", "unknown-fn", "02-fizz", "str.join", "str.implode"),
    ("fizz", "unknown-fn", "02-fizz", "list.range", "list.iota"),
    ("stats", "unknown-fn", "03-stats", "math.max", "math.maximum"),
    ("stats", "unknown-fn", "03-stats", "list.fold", "list.reduce"),
    ("primes", "unknown-fn", "04-primes", "list.filter", "list.select"),
    ("search", "unknown-fn", "06-search", "list.nth", "list.get"),
    ("dot", "unknown-fn", "11-dot", "list.map2", "list.zipwith"),  # retargeted in M7: list.nth left this file
    ("bank", "unknown-fn", "07-bank", "str.from-int", "str.of-int"),
    ("bank", "unknown-fn", "07-bank", "str.concat", "str.append"),
    ("grades", "unknown-fn", "08-grades", "list.sum", "list.sum-all"),
    ("roman", "unknown-fn", "10-roman", "str.concat", "str.cat"),
    ("greet", "unknown-fn", "13-greet", "io.print", "io.println"),
    ("greet", "unknown-prelude", "13-greet", "io.print", "print"),
    ("stats", "unknown-prelude", "03-stats", "(len xs))))", "(length xs))))"),
    ("search", "unknown-prelude", "06-search", "(list.nth xs i)", "(nth xs i)"),  # retargeted in M7: (len xs) left this file
    ("gcd", "unknown-prelude", "12-gcd", "(mod a b)", "(remainder a b)"),
    ("dot", "unknown-prelude", "11-dot", "(= (len xs) (len ys))", "(= (size xs) (len ys))"),
    ("cart", "unknown-module", "01-cart", "(use list)", "(use list set)"),
    ("stats", "missing-use", "03-stats", "(use list math)", "(use list)"),
    ("fizz", "missing-use", "02-fizz", "(use list str)", "(use str)"),
    ("cart", "unknown-field", "01-cart", "(get it price)", "(get it cost)"),
    ("bank", "unknown-field", "07-bank", "(owner name)", "(holder name)"),
    ("cart", "unknown-type", "01-cart", "(List Item)", "(List Items)"),
    ("grades", "unknown-variant", "08-grades", '(Good "B")', '(Great "B")'),
    ("search", "unknown-variant", "06-search", "((Some _) true)", "((Just _) true)"),  # retargeted in M7: (Some i) left this file
    ("perimeter", "unknown-variant", "09-perimeter", "((Square s)", "((Squar s)"),
    ("grades", "non-exhaustive", "08-grades", ' (Failing "F")', ""),
    ("bank", "unknown-error", "07-bank", "(fails InsufficientFunds)", "(fails InsufficientFund)"),
    ("bank", "arity", "07-bank", "(fail InsufficientFunds amount (get acct balance))", "(fail InsufficientFunds amount)"),
    ("cart", "arity", "01-cart", "(* (get it price) (get it qty))", "(* (get it price) (get it qty) 1)"),
    ("collatz", "undeclared-fail", "05-collatz", "(/ n 2)", "(fail OutOfRange)"),
    ("bank", "undeclared-fail", "07-bank", "(fails InsufficientFunds)", ""),  # retargeted: stats can no longer fail (ADR-061 B)
    ("fizz", "undeclared-effect", "02-fizz", "(str.from-int n)", '(let ((u (io.print "x"))) (str.from-int n))'),
    ("greet", "undeclared-effect", "13-greet", "(eff io.out)", ""),
    ("greet", "unknown-effect", "13-greet", "(eff io.out)", "(eff io.write)"),
    ("primes", "float", "04-primes", "(>= n 2)", "(>= n 2.5)"),
    ("roman", "unknown-local-fn", "10-roman", "(step", "(construct"),  # retargeted in M8: build renamed step
    ("cart", "type-mismatch", "01-cart", "(sig (it Item) -> Int)", "(sig (it Item) -> Str)"),
    ("fizz", "type-mismatch", "02-fizz", "(str.from-int n)", "n"),
    ("bank", "type-mismatch", "07-bank", "(> amount 0)", '(> amount "0")'),
    ("stats", "unexported", "03-stats", ("(use list math)", "(- (maximum xs) (minimum xs))"), ("(use list math search)", "(- (maximum xs) (search.go xs 1 0))")),
]
# plausible logic bugs: only `test` can see these (reported separately, not part of S3)
LOGIC = [
    ("cart", "wrong-constant", "01-cart", "=> 750", "=> 751"),
    ("primes", "off-by-one", "04-primes", "(list.range 2 n)", "(list.range 2 (+ n 1))"),
    ("fizz", "swapped-word", "02-fizz", '"Fizz" (if', '"Buzz" (if'),
]


def _mutate(d, old, new):
    src = lm_file(d).read_text()
    pairs = list(zip(old, new)) if isinstance(old, tuple) else [(old, new)]
    for o, n in pairs:
        if o not in src:
            return None
        src = src.replace(o, n)
    return src


def s3(dirs, items, with_test=False):
    by = {d.name: d for d in dirs}
    out = []
    for mod, cat, task, old, new in items:
        d = by[task]
        src = _mutate(d, old, new)
        if src is None:
            out.append({"id": f"{mod}:{cat}", "category": cat, "error": "pattern not found"})
            continue
        tmp = Path(tempfile.mkdtemp())
        try:
            (tmp / lm_file(d).name).write_text(src)
            paths = [str(tmp)] + ([str(by["06-search"])] if cat == "unexported" else [])
            r = subprocess.run([sys.executable, "-m", "lm", "check", *paths], capture_output=True, text=True, cwd=ROOT)
            codes = sorted({json.loads(l)["code"] for l in r.stdout.splitlines() if l.startswith("{") and json.loads(l)["severity"] == "error"})
            rec = {"id": f"{mod}:{cat}", "category": cat, "caught": bool(codes), "codes": codes}
            if with_test and not codes:
                t = subprocess.run([sys.executable, "-m", "lm", "test", str(tmp)], capture_output=True, text=True, cwd=ROOT)
                rec["caught_by_test"] = t.returncode == 1
            out.append(rec)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    return out


def s6():
    r = subprocess.run([sys.executable, "-m", "lm", "accept"], capture_output=True, text=True, cwd=ROOT)
    m = re.search(r"Summary: (\d+) approved \((\d+) pass, (\d+) FAIL\) · (\d+) proposed · guard (\w+)", r.stdout)
    return {"approved": int(m[1]), "pass": int(m[2]), "fail": int(m[3]), "proposed": int(m[4]), "guard": m[5]} if m else {"error": r.stdout}


def s4(dirs):
    first = json.loads((ROOT / "bench/results/s4-attempt1.json").read_text()) if (ROOT / "bench/results/s4-attempt1.json").exists() else {}
    rows = []
    for d in dirs:
        c = subprocess.run([sys.executable, "-m", "lm", "check", str(d)], capture_output=True, text=True, cwd=ROOT)
        t = subprocess.run([sys.executable, "-m", "lm", "test", str(d)], capture_output=True, text=True, cwd=ROOT)
        rows.append({"task": d.name, "green_now": c.returncode == 0 and t.returncode == 0,
                     "green_first_try": first.get(d.name, {}).get("green_first_try"),
                     "first_try_errors": first.get(d.name, {}).get("check_errors", [])})
    return rows


def run_all():
    dirs = task_dirs()
    eq = equivalence(dirs)
    res = {"tasks": len(dirs), "equivalence": eq, "s5": s5(dirs), "s1_s2": s1_s2(dirs), "s3": s3(dirs, H),
           "logic": s3(dirs, LOGIC, with_test=True), "s4": s4(dirs), "s6": s6()}
    out = ROOT / "bench" / "results"
    out.mkdir(parents=True, exist_ok=True)
    (out / "results.json").write_text(json.dumps(res, indent=1, sort_keys=True) + "\n")
    (out / "summary.md").write_text(summary(res))
    return res


def summary(r):
    s5r = r["s5"]
    rf = statistics.median(x["lm"] / x["py_full"] for x in s5r)
    rb = statistics.median(x["lm"] / x["py_bare"] for x in s5r)
    rm = statistics.median(x["lm_merged"] / x["py_full_merged"] for x in s5r)
    h = r["s3"]
    caught = sum(x.get("caught", False) for x in h)
    first = [x for x in r["s4"] if x["green_first_try"] is not None]
    g1 = sum(x["green_first_try"] for x in first)
    g2 = sum(x["green_now"] for x in r["s4"])
    sx = r["s1_s2"]
    dis = sum(len(x["disagree"]) for x in r["equivalence"])
    lg = r["logic"]
    s6r = r["s6"]
    rows = [
        ("S1 slice vs project text", "<= 25% (median)", f"{sx['s1_median']:.1%} (max {sx['s1_max']:.1%}; {sx['functions']} fns, {sx['whole_tokens']} tokens)"),
        ("S2 edit op vs regenerate file", "<= 30% (median)", f"{sx['s2_median']:.1%} (max {sx['s2_max']:.1%})"),
        ("S3 injected hallucinations caught by check", ">= 90%", f"{caught}/{len(h)} = {caught / len(h):.0%}"),
        ("S4 tasks green within 2 iterations", ">= 80%", f"first try {g1}/{len(first)}; within 2: {g2}/{len(r['s4'])} = {g2 / len(r['s4']):.0%}"),
        ("S5 LM tokens vs Python", "<= 1.3x", f"{rf:.2f}x vs Python with docstrings+examples+asserts; {rb:.2f}x vs bare Python"),
        ("S6 approved scenarios pass, guard OK", "100%", f"{s6r.get('pass')}/{s6r.get('approved')} pass, guard {s6r.get('guard')}"),
    ]
    L = ["# LM benchmark summary (generated by `lm bench`)", "", "| Metric | Target | Result |", "|---|---|---|"]
    L += [f"| {a} | {b} | {c} |" for a, b, c in rows]
    L += ["", f"S1 against the module file alone (the Python-style unit of reading): median {sx['s1_module_median']:.1%}, max {sx['s1_module_max']:.1%}.",
          f"S5 sensitivity, punctuation runs counted once (closer to real BPE tokenizers): {rm:.2f}x vs full Python. The decision uses the ADR-012 number above.", "", f"Equivalence: {r['tasks']} tasks, LM and Python agree with the declared expectations on every case: {'yes' if dis == 0 else f'NO ({dis} disagreements)'}.", ""]
    L += ["## S3 misses", ""] + ([f"- {x['id']}" for x in h if not x.get("caught")] or ["- none"])
    L += ["", "## S3 detail (error codes by category)", ""]
    cats: dict = {}
    for x in h:
        cats.setdefault(x["category"], []).append(x)
    for c in sorted(cats):
        L.append(f"- {c}: {sum(y.get('caught', False) for y in cats[c])}/{len(cats[c])} " + ", ".join(sorted({k for y in cats[c] for k in y.get('codes', [])})))
    L += ["", "## Logic bugs (not hallucinations; `check` is not expected to see them)", ""]
    L += [f"- {x['id']}: check {'caught' if x.get('caught') else 'passed'}, test {'caught' if x.get('caught_by_test') else 'passed' if not x.get('caught') else '-'}" for x in lg]
    L += ["", "## S4 first-try failures", ""] + ([f"- {x['task']}: {', '.join(x['first_try_errors'])}" for x in first if not x["green_first_try"]] or ["- none"])
    L += ["", "## S5 per task (tokens)", "", "| task | LM | Python full | Python bare |", "|---|---|---|---|"]
    L += [f"| {x['task']} | {x['lm']} | {x['py_full']} | {x['py_bare']} |" for x in s5r]
    return "\n".join(L) + "\n"
