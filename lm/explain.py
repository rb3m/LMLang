"""`lm explain SYM`: function and type descriptions for a human reviewer."""
from __future__ import annotations

from .printer import flat
from .resolve import head


def _sig(f):
    sig = f.clauses["sig"][0]
    items = sig.items[1:]
    k = next(i for i, x in enumerate(items) if getattr(x, "value", None) == "->")
    takes = [f"{p.items[0].value}: {flat(p.items[1])}" for p in items[:k]]
    return takes, flat(items[k + 1])


def explain_type(idx, t) -> str:
    lines = [t.qual]
    lines.append("Parameters: " + (" ".join(t.params) if t.params else "none"))
    lines.append("Definition: " + flat(t.node))
    callers = sorted({owner for owner, _ in idx.callers(t.qual)})
    used = ", ".join(callers) if callers else "nothing in this project"
    lines.append("Used by:  " + used)
    return "\n".join(lines) + "\n"


def explain(prog, idx, f) -> str:
    takes, ret = _sig(f)
    L = [f"{f.qual} - {f.purpose}"]
    L.append("Takes:    " + ("; ".join(takes) if takes else "nothing"))
    L.append("Returns:  " + ret)
    fl = []
    for eid in sorted(f.fails):
        e = next((m.errors[eid.split(".")[-1]] for m in prog.modules.values() if eid.split(".")[-1] in m.errors and m.errors[eid.split(".")[-1]].id == eid), None)
        flds = ", ".join(f"{x.items[0].value}: {flat(x.items[1])}" for x in e.node.items[2:]) if e is not None and e.node is not None else ""
        fl.append(eid + (f"({flds})" if flds else ""))
    L.append("Can fail: " + (", ".join(fl) if fl else "never"))
    L.append("Effects:  " + (", ".join(sorted(f.eff)) if f.eff else "none (pure)"))
    for h, label in (("requires", "Requires: "), ("ensures", "Ensures:  ")):
        for c in f.clauses.get(h, []):
            L.append(label + flat(c.items[1]))
    exs = f.clauses.get("example", [])
    if exs:
        L.append("Examples:")
        for c in exs:
            args = " ".join(flat(a) for a in c.items[1].items)
            L.append(f"  {f.name}({args}) => {flat(c.items[3])}")
    else:
        L.append("Examples: none" + ("" if f.eff else "  (warning: pure function without examples)"))
    callers = sorted({o for o, _ in idx.callers(f.qual)})
    L.append("Used by:  " + (", ".join(callers) if callers else "nothing in this project"))
    return "\n".join(L) + "\n"
