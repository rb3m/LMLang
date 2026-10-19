"""E-OVERFLOW and E-FLOAT diagnostics built from the interpreter's frame stack (ADR-029, ADR-030 item 5,
ADR-039 item 4: E-FLOAT has the same shape)."""
from __future__ import annotations

import shlex

from .diag import make
from .sexpr import SList
from .tree import Coll
from .values import INT_MAX, INT_MIN, UNIT, Pair, Rec, Var, show, show_coll

GUIDANCE = "Fix the arithmetic, validate input, or add a justified precondition; overflow cannot be caught."
FLOAT_GUIDANCE = ("Fix the arithmetic, validate input, or add a justified precondition; "
                  "a non-finite Float cannot be caught.")
FLOAT_MAX = 1.7976931348623157e+308
# code -> (message lead, bounds, guidance)
KINDS = {"E-OVERFLOW": ("Int overflow", [INT_MIN, INT_MAX], GUIDANCE),
         "E-FLOAT": ("Float result not finite", [-FLOAT_MAX, FLOAT_MAX], FLOAT_GUIDANCE)}
MAX_FRAMES = 3
REPLAY_CAP = 400


def overflow_diag(ex, it):
    """Diagnostic for an Overflow raised while `it` was running; it.frames is the stack at the fault."""
    frames = [fr for fr in it.frames if fr[0] != "top"][::-1]  # innermost first
    names = [_frame_name(fr, it) for fr in frames]
    shown = _pick(names, frames)
    site_mod, site, site_path = _innermost_site(it.frames, it)
    user = _nearest_user(frames)
    replay = _replay(user)
    lead, bounds, guidance = KINDS[ex.code]
    user_path = _path_in(user[1], user[2]) if user is not None and user[2] is not None else None
    data = {"op": ex.op, "operands": list(ex.operands), "bounds": bounds, "frames": shown,
            "frames_omitted": len(names) - len(shown), "user_path": user_path or site_path, "replay": replay}
    where = " <- ".join(shown) if shown else "top level"
    expr = f"({ex.op}" + "".join(" " + show(a) for a in ex.operands) + ")"
    msg = (f"{lead}: {expr} is outside [{show(bounds[0])}, {show(bounds[1])}] in {where}; "
           f"replay: {replay}. {guidance}")
    file = site_mod.file if site_mod is not None else ""
    line, col = (site.line, site.col) if site is not None else (1, 1)
    return make(ex.code, file, line, col, msg, path=site_path, found=expr, data=data)


def _frame_name(fr, it):
    kind, obj = fr[0], fr[1]
    if kind == "fn":
        return obj.qual
    if kind == "cb":
        return f"`{obj.name}` (callback)"
    owner = _owner(obj.mod, obj.body)
    return f"(lam) in {owner.qual}" if owner else "(lam)"


def _pick(names, frames):
    """At most MAX_FRAMES names: the innermost ones, keeping the nearest user frame visible."""
    if len(names) <= MAX_FRAMES:
        return names
    user = next((k for k, fr in enumerate(frames) if _is_user(fr)), None)
    if user is None or user < MAX_FRAMES:
        return names[:MAX_FRAMES]
    return names[:MAX_FRAMES - 1] + [names[user]]


def _is_user(fr):
    return fr[0] == "fn" and not fr[1].mod.is_stdlib


def _nearest_user(frames):
    fns = [fr for fr in frames if fr[0] == "fn"]
    return next((fr for fr in fns if _is_user(fr)), fns[-1] if fns else None)


def _innermost_site(frames, it):
    """(module, node, path) of the innermost call site with a known location."""
    for fr in reversed(frames):
        site = fr[2]
        if site is None or fr[0] == "top":
            continue
        mod = fr[1].mod
        owner = fr[1] if fr[0] == "fn" else _owner(mod, site)
        return mod, site, (_path_in(owner, site) if owner else "")
    return None, None, ""


def _owner(mod, node):
    return next((f for f in mod.fns.values() if _path_in(f, node) is not None), None)


def _path_in(f, target):
    base = f"{f.mod.name}/{f.name}"
    for kind, clauses in f.clauses.items():
        for k, c in enumerate(clauses):
            found = _find(c, target, f"{base}/{kind}" if kind == "body" else f"{base}/{kind}#{k}")
            if found is not None:
                return found
    return None


def _find(node, target, path):
    if node is target:
        return path
    if not isinstance(node, SList):
        return None
    for i, child in enumerate(node.items):
        found = _find(child, target, f"{path}/{i}")
        if found is not None:
            return found
    return None


# ---- replay ------------------------------------------------------------------------------------
class _NoRepr(Exception):
    pass


def _replay(fr):
    if fr is None:
        return "unavailable (no function call on the stack)"
    f, args = fr[1], fr[3]
    try:
        texts = [_const(v, f.mod) for v in args]
    except _NoRepr as why:
        return f"unavailable ({why})"
    words = ["python3", "-m", "lm", "run", f.qual] + texts
    for e in sorted(f.eff):
        words += ["--allow", e]
    cmd = " ".join(shlex.quote(w) for w in words)
    return cmd if len(cmd) <= REPLAY_CAP else f"unavailable (arguments exceed {REPLAY_CAP} characters)"


def _const(v, mod):
    """LM source text that evaluates to v inside `mod`, or _NoRepr."""
    if v is True or v is False or isinstance(v, (int, float, str)) or v is UNIT:
        return show(v)
    if isinstance(v, tuple):
        return "(list" + "".join(" " + _const(x, mod) for x in v) + ")"
    if isinstance(v, Var):
        name = _local(v.mod, v.name, mod)
        return f"({name}" + "".join(" " + _const(a, mod) for a in v.args) + ")" if v.args else name
    if isinstance(v, Rec):
        q, n = v.t.split(".", 1)
        return f"(new {_local(q, n, mod)}" + "".join(f" ({k} {_const(x, mod)})" for k, x in v.items) + ")"
    if isinstance(v, Pair):
        return f"(pair {_const(v.a, mod)} {_const(v.b, mod)})"
    if isinstance(v, Coll):
        return show_coll(v, lambda x: _const(x, mod))
    raise _NoRepr("an argument is a function value")


def _local(q, name, mod):
    if q in ("", mod.name):
        return name
    if q in {u.value for u in mod.uses}:
        return f"{q}.{name}"
    raise _NoRepr(f"an argument holds a value of module `{q}`, not used by `{mod.name}`")
