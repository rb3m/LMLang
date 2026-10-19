"""Context-cheap queries over a checked Program: index, slice, callers, deps, hash."""
from __future__ import annotations

import hashlib
import re

from .printer import _block, flat, print_module, render
from .resolve import head, suggest
from .sexpr import Atom, SList

TOKEN_RE = re.compile(r"\w+|[^\w\s]")
# Clauses of a callee's signature block in a slice: its complete contract minus examples (ADR-028).
SIG_BLOCK = ("purpose", "sig", "eff", "fails", "requires", "ensures")


def tokens(text: str) -> int:
    """Token heuristic (ADR-012): word pieces + punctuation."""
    return len(TOKEN_RE.findall(text))


class Symbol:
    def __init__(self, kind, mod, name, info):
        self.kind, self.mod, self.name, self.info = kind, mod, name, info

    @property
    def qual(self):
        return f"{self.mod.name}.{self.name}"


class Index:
    def __init__(self, prog):
        self.prog = prog
        self.edges: dict = {}  # owner qual -> [(target qual, node path)]
        for (mod, path), target in sorted(prog.refs.items()):
            segs = path.split("/")
            t = self.norm(target)
            if len(segs) > 1 and t is not None and f"{segs[0]}.{segs[1]}" != t:
                self.edges.setdefault(f"{segs[0]}.{segs[1]}", []).append((t, path))

    # ---- symbols -----------------------------------------------------------------------------
    def norm(self, target):
        if "." not in target or target.startswith("prelude."):
            return None
        mn, nm = target.split(".", 1)
        m = self.prog.modules.get(mn)
        if m is None:
            return None
        if nm[:1].islower():
            return target if (nm in m.fns or nm in m.consts) else None
        hit = m.caps.get(nm)
        if hit is None:
            return None
        return f"{mn}.{hit[1].tname}" if hit[0] == "variant" else target

    def kind(self, q):
        mn, nm = q.split(".", 1)
        m = self.prog.modules[mn]
        return "fn" if nm in m.fns else "const" if nm in m.consts else "type" if nm in m.types else "error" if nm in m.errors else None

    def find(self, text):
        """-> (Symbol | None, error message)."""
        if "." not in text:
            return None, "symbol must be written module.name"
        mn, nm = text.split(".", 1)
        m = self.prog.modules.get(mn)
        if m is None:
            return None, f"no module `{mn}`" + (f"; did you mean {' '.join(suggest(mn, self.prog.available))}" if suggest(mn, self.prog.available) else "")
        if nm in m.fns:
            return Symbol("fn", m, nm, m.fns[nm]), ""
        if nm in m.consts:
            return Symbol("const", m, nm, m.consts[nm]), ""
        if nm in m.types:
            return Symbol("type", m, nm, m.types[nm]), ""
        if nm in m.errors:
            return Symbol("error", m, nm, m.errors[nm]), ""
        if nm in m.variants:
            t = m.types[m.variants[nm].tname]
            return Symbol("type", m, t.name, t), ""
        cands = [f"{mn}.{n}" for n in list(m.fns) + list(m.consts) + list(m.types) + list(m.errors)]
        return None, f"module `{mn}` has no symbol `{nm}`; did you mean: {' '.join(suggest(text, cands) or sorted(cands)[:6])}"

    # ---- index -----------------------------------------------------------------------------------
    def module_lines(self, mods):
        out = []
        for m in mods:
            n = len(m.exported_fns) + len(m.exported_consts) + len(m.exported_caps)
            out.append(f'{m.name}  {n} exports  {m.purpose or ""}')
        return out

    def index_lines(self, mods, exported_only=False):
        out = []
        for m in mods:
            use = f"  (use {' '.join(u.value for u in m.uses)})" if m.uses else ""
            out.append(f"module {m.name}  -- {m.purpose or ''}{use}")
            for c in m.root.items[2:]:
                h = head(c)
                if h not in ("type", "error", "const", "fn"):
                    continue
                nm = c.items[1].value
                exp = nm in m.exported_consts if h == "const" else nm in m.exported_fns if h == "fn" else nm in m.exported_caps
                if exported_only and not exp:
                    continue
                mark = "*" if exp else " "
                if h == "const":
                    ci = m.consts[nm]
                    t_str = flat(ci.clauses["type"][0].items[1]) if "type" in ci.clauses else "?"
                    from .values import show
                    val_str = show(ci.value) if ci.value is not None else (flat(ci.clauses["value"][0].items[1]) if "value" in ci.clauses else "?")
                    out.append(f"{mark}const {m.name}.{nm}  {t_str} = {val_str}  -- {ci.purpose}")
                elif h == "fn":
                    f = m.fns[nm]
                    sig = " ".join(flat(x) for x in f.clauses["sig"][0].items[1:]) if "sig" in f.clauses else "?"
                    extra = "".join(f"  [{k} {' '.join(a.value for a in f.clauses[k][0].items[1:])}]" for k in ("eff", "fails") if k in f.clauses)
                    out.append(f"{mark}fn {m.name}.{nm}  {sig}{extra}  -- {f.purpose}")
                elif h == "type":
                    body = c.items[2:]
                    out.append(f"{mark}type {m.name}.{nm}  {flat(body[0]) if body else '?'}")
                else:
                    out.append(f"{mark}error {m.name}.{nm}  {' '.join(flat(x) for x in c.items[2:])}".rstrip())
        return out

    # ---- graph queries -----------------------------------------------------------------------------
    def callers(self, q):
        return sorted((o, p) for o, es in self.edges.items() for t, p in es if t == q)

    def deps(self, q, depth):
        seen, frontier = {}, [q]
        for d in range(1, depth + 1):
            nxt = []
            for x in frontier:
                for t, _ in self.edges.get(x, []):
                    if t != q and t not in seen:
                        seen[t] = d
                        nxt.append(t)
            frontier = nxt
        return sorted(seen.items(), key=lambda kv: (kv[1], kv[0]))

    # ---- slice ---------------------------------------------------------------------------------------
    def _closure(self, q, prio, items):
        if q in items and items[q][0] <= prio:
            return
        items[q] = (prio, "full")
        for t, _ in self.edges.get(q, []):
            if self.kind(t) in ("type", "error", "const"):
                self._closure(t, prio, items)

    def _sig_edges(self, q):
        return [t for t, p in self.edges.get(q, []) if p.split("/")[2:3] and p.split("/")[2].split("#")[0] in SIG_BLOCK]

    def collect(self, root, bodies=False, depth=1):
        items = {root: (0, "full")}
        if self.kind(root) != "fn":
            for t, _ in self.edges.get(root, []):
                if self.kind(t) in ("type", "error", "const"):
                    self._closure(t, 1, items)
            return items
        level_nodes = [root]
        for level in range(1, (depth if bodies else 1) + 1):
            nxt = []
            for q in level_nodes:
                for t, _ in self.edges.get(q, []):
                    k = self.kind(t)
                    if k in ("type", "error", "const"):
                        self._closure(t, level, items)
                    elif k == "fn" and t not in items:
                        items[t] = (level, "full" if bodies else "sig")
                        nxt.append(t)
            for q in nxt:
                for t in self._sig_edges(q):
                    if self.kind(t) in ("type", "error", "const"):
                        self._closure(t, level, items)
            level_nodes = nxt
        return items

    def _node(self, q, form):
        mn, nm = q.split(".", 1)
        m = self.prog.modules[mn]
        if q in {f"{mn}.{n}" for n in m.fns} and form == "sig":
            f = m.fns[nm]
            keep = [c for c in f.node.items[2:] if head(c) in SIG_BLOCK]
            return SList((f.node.items[0], f.node.items[1], *keep))
        for c in m.root.items[2:]:
            if head(c) in ("type", "error", "const", "fn") and c.items[1].value == nm:
                return c

    def render_items(self, items):
        out = []
        for mn in sorted({q.split(".", 1)[0] for q in items}):
            m = self.prog.modules[mn]
            kids = []
            for c in m.root.items[2:]:
                h = head(c)
                if h == "purpose":
                    kids.append(c)
                elif h in ("type", "error", "const", "fn"):
                    q = f"{mn}.{c.items[1].value}"
                    if q in items:
                        kids.append(self._node(q, items[q][1]))
            out.append(print_module(SList((Atom("sym", "module"), Atom("sym", mn), *kids))))
        return "".join(out)

    def slice(self, root, bodies=False, depth=1, budget=None):
        items = self.collect(root, bodies, depth)
        text = self.render_items(items)
        dropped = []
        while budget is not None and tokens(text) > budget and len(items) > 1:
            worst = max(p for p, _ in items.values())
            if worst == 0:
                break
            for q in [q for q, (p, _) in items.items() if p == worst]:
                dropped.append(q)
                del items[q]
            text = self.render_items(items)
        return text, items, sorted(dropped)

    # ---- hash ----------------------------------------------------------------------------------------------
    def hash(self, q):
        node = self._node(q, "full")
        if head(node) == "fn":
            node = SList((node.items[0], node.items[1], *[c for c in node.items[2:] if head(c) not in ("purpose", "example")]))
            text = _block(node, 0)
        elif head(node) == "const":
            node = SList((node.items[0], node.items[1], *[c for c in node.items[2:] if head(c) != "purpose"]))
            text = render(node, 0)
        else:
            text = render(node, 0)
        return hashlib.sha256(text.encode()).hexdigest()[:8]
