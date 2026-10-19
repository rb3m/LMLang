"""Acceptance scenarios: human-owned oracle (docs/TESTING.md). Files: tests/accept/*.accept, lock: accept.lock."""
from __future__ import annotations

import datetime
import hashlib
import io
from pathlib import Path

from .interp import Interp
from .printer import flat
from .runner import in_big_stack
from .sexpr import Atom, SList, read
from .values import LmFail, Named, show

EXPECTS = ("expect", "expect-fail", "expect-out")


class Scenario:
    def __init__(self, node, file):
        self.node, self.file, self.problem = node, file, None
        self.name = self.status = self.why = None
        self.allow, self.run, self.exp = [], None, None
        self.status_atom = None
        seen = set()
        it = node.items if isinstance(node, SList) else ()
        if not (len(it) >= 2 and getattr(it[0], "value", None) == "scenario" and isinstance(it[1], Atom) and it[1].kind == "str"):
            self.name = f"<bad scenario at {file}:{getattr(node, 'line', 0)}>"
            self.problem = 'scenario must look like (scenario "name" (status ..) (why ..) (run ..) (expect ..))'
            return
        self.name = it[1].value
        for c in it[2:]:
            h = c.items[0].value if isinstance(c, SList) and c.items and isinstance(c.items[0], Atom) else None
            if h in ("status", "why") and h in seen:
                self.problem = f"unexpected or duplicate clause {flat(c)}"
                continue
            seen.add(h)
            if h == "status" and len(c.items) == 2:
                self.status = getattr(c.items[1], "value", None)
                self.status_atom = c.items[1] if isinstance(c.items[1], Atom) else None
            elif h == "why" and len(c.items) == 2 and isinstance(c.items[1], Atom) and c.items[1].kind == "str":
                self.why = c.items[1].value
            elif h == "allow":
                if len(c.items) != 2:
                    self.problem = "write one effect per clause: " + " ".join(
                        f"(allow {flat(n)})" for n in c.items[1:])
                    continue
                if not (isinstance(c.items[1], Atom)
                        and c.items[1].kind == "sym"):
                    self.problem = "(allow EFF) needs one effect name"
                    continue
                self.allow.append(c.items[1].value)
            elif h == "run" and len(c.items) >= 2 and self.run is None:
                self.run = c
            elif h in EXPECTS and self.exp is None:
                self.exp = c
            else:
                self.problem = f"unexpected or duplicate clause {flat(c)}"
        if self.problem is None:
            if self.status not in ("proposed", "approved"):
                self.problem = "status must be (status proposed) or (status approved)"
            elif not self.why:
                self.problem = "missing (why \"...\")"
            elif self.run is None or self.exp is None:
                self.problem = "needs one (run ..) and one of (expect ..) (expect-fail ..) (expect-out ..)"
            elif not (isinstance(self.run.items[1], Atom) and self.run.items[1].kind == "sym" and "." in self.run.items[1].value):
                self.problem = "(run module.fn args..) expects a qualified function name"
            elif self.exp.items[0].value == "expect-out" and not (
                    len(self.exp.items) == 2
                    and isinstance(self.exp.items[1], Atom)
                    and self.exp.items[1].kind == "str"):
                self.problem = "expect-out needs exactly one string"
            elif self.exp.items[0].value == "expect" and len(self.exp.items) != 2:
                self.problem = "expect needs exactly one value"
            elif self.exp.items[0].value == "expect-fail" and len(self.exp.items) < 2:
                self.problem = "expect-fail needs an error name and its field arguments"

    @property
    def module(self):
        return self.run.items[1].value.split(".", 1)[0] if self.problem is None else None

    def digest(self) -> str:
        """Hash of the meaning (status excluded, so approving does not change it)."""
        kept = [i for i in self.node.items if not (isinstance(i, SList) and i.items and getattr(i.items[0], "value", "") == "status")]
        return hashlib.sha256(flat(SList(tuple(kept))).encode()).hexdigest()[:16]

    def describe(self) -> str:
        a = " ".join(flat(x) for x in self.run.items[2:])
        call = f"{self.run.items[1].value}({a})"
        e = self.exp
        return f"{call} " + {"expect": "= " + flat(e.items[1]) if len(e.items) > 1 else "",
                               "expect-fail": "fails " + " ".join(flat(x) for x in e.items[1:]),
                               "expect-out": "prints " + flat(e.items[1])}[e.items[0].value]


def load_scenarios(d):
    out, bad = [], []
    for f in sorted(Path(d).glob("*.accept")) if Path(d).is_dir() else []:
        node, diags = read(f.read_text(encoding="utf-8"), str(f))
        if node is None:
            bad.append(f"{f}: {diags[0].msg}")
            continue
        if not (isinstance(node, SList) and node.items and getattr(node.items[0], "value", None) == "scenarios"):
            bad.append(f"{f}: file must be one (scenarios (scenario ..) ..) form")
            continue
        out += [Scenario(n, str(f)) for n in node.items[1:]]
    seen = set()
    for s in out:
        if s.name in seen and s.problem is None:
            s.problem = f"duplicate scenario name {s.name!r}"
        seen.add(s.name)
    return out, bad


def read_lock_raw(path):
    raw = {}
    p = Path(path)
    if p.is_file():
        for line in p.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            entry, sep, suff = line.partition("\t#")
            h, _, name = entry.partition(" ")
            raw[name] = (h, sep + suff if sep else "")
    return raw


def read_lock(path):
    return {name: h for name, (h, _) in read_lock_raw(path).items()}


def write_lock(path, scs):
    raw = read_lock_raw(path)
    lines = []
    for s in scs:
        if s.status == "approved" and s.problem is None:
            dig = s.digest()
            old_dig, old_suff = raw.get(s.name, (None, ""))
            suff = old_suff if old_dig == dig else ""
            lines.append(f"{dig} {s.name}{suff}")
    lines.sort()
    Path(path).write_text("".join(l + "\n" for l in lines), encoding="utf-8")


def _check_approval(digests, by_text):
    if not by_text or not by_text.strip():
        raise ValueError("--by text cannot be empty")
    if "\n" in by_text or "\r" in by_text:
        raise ValueError("--by text must not contain newlines")
    if not digests:
        raise ValueError("at least one DIGEST or NAME required")


def _flip_status(lines, s):
    """Rewrite the `proposed` atom of scenario s to `approved` in place, using its source position."""
    a = s.status_atom
    i, j = a.line - 1, a.col - 1
    if not (0 <= i < len(lines) and lines[i][j:j + 8] == "proposed"):
        raise ValueError(f"cannot locate the status of scenario '{s.name}' in {s.file}")
    lines[i] = lines[i][:j] + "approved" + lines[i][j + 8:]


def _write_statuses(scs):
    by_file = {}
    for s in scs:
        by_file.setdefault(s.file, []).append(s)
    for fpath, group in by_file.items():
        lines = Path(fpath).read_text(encoding="utf-8").splitlines(keepends=True)
        for s in group:
            _flip_status(lines, s)
        Path(fpath).write_text("".join(lines), encoding="utf-8")


def approve(scs, lock_path, digests, by_text):
    """Approve the scenarios whose digests the owner reviewed, recording their words (ADR-055); return (approved, already)."""
    _check_approval(digests, by_text)
    by_dig = {s.digest(): s for s in scs if s.problem is None}
    unknown = [d for d in digests if d not in by_dig]
    if unknown:
        raise ValueError(f"unknown scenario digest '{unknown[0]}' (changed since review?)")
    raw_lock = read_lock_raw(lock_path)
    chosen = [by_dig[d] for d in dict.fromkeys(digests)]
    already = [s for s in chosen if s.status == "approved" and raw_lock.get(s.name, (None,))[0] == s.digest()]
    todo = [s for s in chosen if s not in already]
    _write_statuses([s for s in todo if s.status == "proposed"])
    today = datetime.date.today().isoformat()
    for s in todo:
        s.status = "approved"
        raw_lock[s.name] = (s.digest(), f'\t# approved {today} by owner: "{by_text}"')
    if todo:
        _write_lock_raw(lock_path, raw_lock)
    return todo, already


def _write_lock_raw(lock_path, raw_lock):
    p = Path(lock_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("".join(f"{d} {n}{suff}\n" for n, (d, suff) in sorted(raw_lock.items(), key=lambda kv: f"{kv[1][0]} {kv[0]}")), encoding="utf-8")


def retire(scs, lock_path, names, by_text):
    """Drop lock entries of scenarios the owner agreed to retire (renamed or deleted); return [(name, digest)]."""
    _check_approval(names, by_text)
    raw_lock = read_lock_raw(lock_path)
    existing = {s.name for s in scs}
    for n in names:
        if n not in raw_lock:
            raise ValueError(f"'{n}' is not in the lock")
        if n in existing:
            raise ValueError(f"scenario '{n}' still exists; only renamed or deleted scenarios can be retired")
    retired = [(n, raw_lock.pop(n)[0]) for n in dict.fromkeys(names)]
    _write_lock_raw(lock_path, raw_lock)
    return retired


def guard(scs, lock):
    """Return problem lines. Approved scenarios must match the lock exactly."""
    probs, by = [], {s.name: s for s in scs}
    for name, h in sorted(lock.items()):
        s = by.get(name)
        if s is None:
            probs.append(f"MISSING   {name}: locked scenario no longer exists")
        elif s.status != "approved":
            probs.append(f"UNAPPROVED {name}: locked scenario is no longer approved")
        elif s.problem is None and s.digest() != h:
            probs.append(f"CHANGED   {name}: content differs from accept.lock")
    for s in scs:
        if s.problem:
            probs.append(f"INVALID   {s.name}: {s.problem}")
        if s.status == "approved" and s.name not in lock:
            probs.append(f"UNBLESSED {s.name}: approved but not in accept.lock (human must run `lm accept --bless`)")
    return probs


def strip_own_module(node, mname: str):
    """Rewrite atoms `M.x` (M = mname) to `x`, preserving line/col. Leaves strings and other modules untouched (backlog 12)."""
    if isinstance(node, SList):
        return SList(tuple(strip_own_module(item, mname) for item in node.items), node.line, node.col)
    prefix = mname + "."
    own = isinstance(node, Atom) and node.kind != "str" and isinstance(node.value, str) and node.value.startswith(prefix) and len(node.value) > len(prefix)
    if not own:
        return node
    return Atom(node.kind, node.value[len(prefix):], node.line, node.col, node.raw)


def external_value(ck, m, node, path):
    """Require qualified module names throughout an outside constant, then normalize."""
    def check(n, p):
        if isinstance(n, SList):
            for k, item in enumerate(n.items):
                check(item, f"{p}/{k}")
        elif isinstance(n, Atom) and n.kind != "str" and isinstance(n.value, str) and (n.value in m.caps or n.value in m.consts):
            qualified = f"{m.name}.{n.value}"
            ck.diag(m, "E-NAME-UNRESOLVED", n, p,
                    f"outside a module write its names qualified: `{qualified}`",
                    expected=qualified, found=n.value,
                    fix=[{"op": "replace-ref", "path": p, "to": qualified}])

    check(node, path)
    return strip_own_module(node, m.name)


def check_args(ck, m, f, raw_nodes):
    """Normalize and check a list of argument nodes against a function's parameters."""
    nodes = [external_value(ck, m, n, f"arg#{k}") for k, n in enumerate(raw_nodes)]
    ck.effs, ck.frames, ck.cur_fn = {}, [{}], None
    ck.constraints, ck.eq_checks = [], []
    ft = ck.fn_type(f)
    for k, (n, pt) in enumerate(zip(nodes, ft[1])):
        ck.clear_facts()
        t = ck.sandbox(m, "an argument", lambda n=n, k=k: ck.infer(m, n, {}, f"arg#{k}"))
        ck.expect(m, pt, t, n, f"arg#{k}", f"argument {k + 1}")
    if nodes:
        ck.note_keys(ft, nodes[0], "arg#0")
    ck.check_constraints(m)
    return nodes, ft


def execute(prog, ck, s):
    """Run one scenario. Returns (ok: bool, detail: str)."""
    prepared, problem = validate(prog, ck, s)
    if problem:
        return False, problem
    m, f, nodes, kind, exp_node, want_node = prepared
    buf = io.StringIO()
    it = Interp(prog, allowed=s.allow, contracts=True, out=buf)
    fv = Named(f)

    def go():
        try:
            args = [it.ev(n, {}, m) for n in nodes]
            return "ok", it.apply(fv, args)
        except LmFail as x:
            return "fail", x
        except Exception as ex:
            from .runner import runtime_diag
            d = runtime_diag(ex, it=it)
            if d is None:
                raise
            return "diag", d

    k, val = in_big_stack(go)
    if k == "diag":
        return False, val.msg
    shown = show(val) if k == "ok" else f"(fail {val.id}" + "".join(" " + show(a) for a in val.args_) + ")"
    if kind == "expect-out":
        want = s.exp.items[1].value
        return (buf.getvalue() == want and k == "ok"), f"printed {buf.getvalue()!r}" + ("" if k == "ok" else f", then {shown}")
    if kind == "expect-fail":
        try:
            want = in_big_stack(lambda: it.fail_value(want_node, {}, m))
        except Exception as ex:
            return False, f"bad expect-fail: {ex}"
        ok = k == "fail" and (val.id, val.args_) == (want.id, want.args_)
        return ok, ("" if ok else f"got {shown}")
    want = in_big_stack(lambda: it.ev(exp_node, {}, m))
    ok = k == "ok" and val == want and type(val) is type(want)
    return ok, ("" if ok else f"got {shown}")


def validate(prog, ck, s):
    """Validate without evaluation; return prepared inputs and a problem."""
    from .accept_validate import validate as validate_scenario

    return validate_scenario(prog, ck, s)
