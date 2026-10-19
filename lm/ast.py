"""Module structure: validate shape and canonicalize clause order (docs/SPEC.md sections 2-3).

Expressions stay as s-expr nodes (path-addressable); typed views arrive with M1.
"""
from __future__ import annotations

import re

from .diag import make
from .sexpr import Atom, SList

MODULE_ORDER = {"purpose": 0, "use": 1, "export": 2, "type": 3, "error": 4, "const": 5, "fn": 6}
CONST_ORDER = {"purpose": 0, "type": 1, "value": 2}
FN_ORDER = {"purpose": 0, "sig": 1, "eff": 2, "fails": 3, "requires": 4, "ensures": 5, "example": 6, "body": 7}
FN_SINGLE = {"purpose", "sig", "eff", "fails", "body"}
MODULE_SINGLE = {"purpose", "use", "export"}
NAME_RE = re.compile(r"[a-z][a-z0-9-]*")
TYPE_NAME_RE = re.compile(r"[A-Z][A-Za-z0-9]*")


def _sym(v: str) -> Atom:
    return Atom("sym", v)


def _head(n):
    if isinstance(n, SList) and n.items and isinstance(n.items[0], Atom) and n.items[0].kind == "sym":
        return n.items[0].value
    return None


def _is_name(n, rx) -> bool:
    return isinstance(n, Atom) and n.kind in ("sym", "type") and rx.fullmatch(str(n.value)) is not None


def canonicalize(root, file: str = ""):
    """Return (canonical module SList | None, diagnostics)."""
    diags: list = []

    def err(code, node, msg, **kw):
        diags.append(make(code, file, node.line, node.col, msg, **kw))

    if _head(root) != "module":
        err("E-PARSE", root, "file must be a single (module ...) form")
        return None, diags
    if len(root.items) < 2 or not _is_name(root.items[1], NAME_RE):
        err("E-PARSE", root, "module needs a lowercase-kebab name, e.g. (module billing ...)")
        return None, diags
    mname = root.items[1].value

    def name_list(clause, rx_ok, what, keep_empty=False):
        """Sorted unique atoms of a list clause; empty -> None unless keep_empty."""
        seen, out = set(), []
        for a in clause.items[1:]:
            if not (isinstance(a, Atom) and a.kind in ("sym", "type") and rx_ok(a)):
                err("E-PARSE", a, f"bad entry in ({clause.items[0].value} ...): expected {what}")
                continue
            if a.value in seen:
                err("E-DUP-NAME", a, f"duplicate `{a.value}` in ({clause.items[0].value} ...)")
                continue
            seen.add(a.value)
            out.append(a)
        out.sort(key=lambda a: a.value)
        return SList((clause.items[0], *out)) if (out or keep_empty) else None

    plain = lambda a: "." not in a.value
    module_name = lambda a: a.kind == "sym" and "." not in a.value
    mod_clauses: dict = {}
    decls: dict = {"type": {}, "error": {}, "const": {}, "fn": {}}
    for c in root.items[2:]:
        h = _head(c)
        if h not in MODULE_ORDER:
            err("E-PARSE", c, f"unknown module clause `{h if h else '?'}`; allowed: {', '.join(MODULE_ORDER)}")
            continue
        if h in MODULE_SINGLE:
            if h in mod_clauses:
                err("E-PARSE", c, f"duplicate `{h}` clause")
                continue
            if h == "purpose":
                if len(c.items) != 2 or not (isinstance(c.items[1], Atom) and c.items[1].kind == "str"):
                    err("E-PARSE", c, "purpose takes exactly one string")
                    continue
                mod_clauses[h] = c
            else:
                mod_clauses[h] = name_list(c, module_name if h == "use" else plain, "a lowercase module name" if h == "use" else "an unqualified name", keep_empty=(h == "export"))
            continue
        # type / error / const / fn: (head Name ...)
        rx = NAME_RE if h in ("fn", "const") else TYPE_NAME_RE
        if len(c.items) < 2 or not _is_name(c.items[1], rx):
            err("E-PARSE", c, f"({h} ...) needs a {'lowercase-kebab' if h in ('fn', 'const') else 'Capitalized'} name")
            continue
        nm = c.items[1].value
        if nm in decls[h]:
            err("E-DUP-NAME", c.items[1], f"duplicate {h} `{nm}`")
            continue
        if h in ("fn", "const") and (nm in decls["fn"] or nm in decls["const"]):
            err("E-DUP-NAME", c.items[1], f"duplicate value name `{nm}` (collides with {'fn' if h == 'const' else 'const'})")
            continue
        if h == "fn":
            decls[h][nm] = _canon_fn(c, file, diags)
        elif h == "const":
            decls[h][nm] = _canon_const(c, file, diags)
        else:
            decls[h][nm] = c

    if any(d.severity == "error" for d in diags):
        return None, diags

    out = [root.items[0], root.items[1]]
    for h in ("purpose", "use", "export"):
        if mod_clauses.get(h) is not None:
            out.append(mod_clauses[h])
    for h in ("type", "error", "const", "fn"):
        out.extend(decls[h][k] for k in sorted(decls[h]))
    return SList(tuple(out)), diags


def _canon_const(c, file, diags):
    def err(code, node, msg):
        diags.append(make(code, file, node.line, node.col, msg))

    seen: set = set()
    clauses = []
    for k in c.items[2:]:
        h = _head(k)
        if h not in CONST_ORDER:
            err("E-PARSE", k, f"unknown const clause `{h if h else '?'}`; allowed: {', '.join(CONST_ORDER)}")
            continue
        if h in seen:
            err("E-PARSE", k, f"duplicate `{h}` clause")
            continue
        seen.add(h)
        if h == "purpose":
            if not (len(k.items) == 2 and isinstance(k.items[1], Atom) and k.items[1].kind == "str"):
                err("E-PARSE", k, "purpose takes exactly one string")
                continue
            text = k.items[1].value
            if "\n" in text or len(text) > 100:
                err("E-PURPOSE-LONG", k, "purpose must be one line of at most 100 characters", expected="<= 100", found=str(len(text)))
                continue
        elif h in ("type", "value"):
            if len(k.items) != 2:
                err("E-PARSE", k, f"({h} ...) takes exactly one {h}")
                continue
        clauses.append(k)
    for need in ("purpose", "type", "value"):
        if need not in seen:
            err("E-PARSE", c, f"const `{c.items[1].value}` is missing its ({need} ...) clause")
    clauses.sort(key=lambda k: CONST_ORDER[_head(k)])
    return SList((c.items[0], c.items[1], *clauses), c.line, c.col)


def _canon_fn(c, file, diags):
    def err(code, node, msg):
        diags.append(make(code, file, node.line, node.col, msg))

    seen: set = set()
    clauses = []
    for k in c.items[2:]:
        h = _head(k)
        if h not in FN_ORDER:
            err("E-PARSE", k, f"unknown fn clause `{h if h else '?'}`; allowed: {', '.join(FN_ORDER)}")
            continue
        if h in FN_SINGLE and h in seen:
            err("E-PARSE", k, f"duplicate `{h}` clause")
            continue
        seen.add(h)
        if h == "purpose" and not (len(k.items) == 2 and isinstance(k.items[1], Atom) and k.items[1].kind == "str"):
            err("E-PARSE", k, "purpose takes exactly one string")
            continue
        if h in ("eff", "fails"):
            names, dup = [], set()
            for a in k.items[1:]:
                if not (isinstance(a, Atom) and a.kind in ("sym", "type")):
                    err("E-PARSE", a, f"bad entry in ({h} ...): expected a name")
                elif a.value in dup:
                    err("E-DUP-NAME", a, f"duplicate `{a.value}` in ({h} ...)")
                else:
                    dup.add(a.value)
                    names.append(a)
            if not names:
                continue  # empty eff/fails clause is dropped (canonical = absent)
            names.sort(key=lambda a: a.value)
            k = SList((k.items[0], *names), k.line, k.col)
        clauses.append(k)
    clauses.sort(key=lambda k: FN_ORDER[_head(k)])  # stable: keeps requires/ensures/example order
    return SList((c.items[0], c.items[1], *clauses), c.line, c.col)
