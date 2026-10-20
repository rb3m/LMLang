"""Symbols, name lookup with diagnostics, and type-expression resolution."""
from __future__ import annotations

import difflib
import re

from .diag import make
from .generics import GenericMixin, declaration_name
from .prelude import EFFECTS, RESERVED_CAPS, RESERVED_VALUES, VALUES
from .program import ConstInfo, ErrInfo, FnInfo, ModInfo, Program, TypeInfo, VariantInfo
from .sexpr import Atom, SList
from .types import BASE, Subst, fn, opt, var

FN_NAME = re.compile(r"[a-z][a-z0-9-]*")


def head(n):
    return n.items[0].value if isinstance(n, SList) and n.items and isinstance(n.items[0], Atom) else None


def suggest(name, cands, n=5):
    return difflib.get_close_matches(name, sorted(set(cands)), n=n, cutoff=0.6)


class Resolver(GenericMixin):
    def __init__(self, prog: Program):
        self.prog = prog
        self.s = Subst()
        self.prelude = self._prelude()

    # ---- diagnostics -------------------------------------------------------------------
    def diag(self, mod, code, node, path, msg, expected="", found="", fix=None, near=None):
        if not mod.report:
            return
        src = node if getattr(node, "line", 0) else near
        line, col = (src.line, src.col) if src is not None and src.line else (1, 1)
        self.prog.diags.append(make(code, mod.file, line, col, msg, path=path, expected=expected, found=found, fix=fix))

    def _prelude(self) -> ModInfo:
        m = ModInfo(name="", file="<prelude>", is_stdlib=True, is_target=False, root=None)
        a = var("a")
        for nm, fields, t in (("Some", [("value", a)], opt(a)), ("None", [], opt(a))):
            v = VariantInfo(m, nm, "Opt", fields, t)
            m.variants[nm] = v
            m.caps[nm] = ("variant", v)
        for nm in ("DivZero", "OutOfRange"):
            e = ErrInfo(m, nm, None, [])
            m.errors[nm] = e
            m.caps[nm] = ("error", e)
        return m

    # ---- pass 1-3: build symbol tables ---------------------------------------------------
    def build(self):
        mods = [self.prog.modules[n] for n in sorted(self.prog.modules)]
        for m in mods:
            self._names(m)
        for m in mods:
            self._exports(m)
        for m in mods:
            self.classify_types(m)
        self.check_regular_recursion()
        for m in mods:
            self._decls(m)
        for m in mods:
            self._sigs(m)
        self.check_declared_keys()

    def _reserved_cap(self, m, nm, node, path):
        if nm in RESERVED_CAPS:
            self.diag(m, "E-DUP-NAME", node, path, f"`{nm}` is reserved by the prelude")
            return True
        if nm in m.caps:
            self.diag(m, "E-DUP-NAME", node, path, f"`{nm}` is already declared in module {m.name}")
            return True
        return False

    def _names(self, m: ModInfo):
        for c in m.root.items[2:]:
            h = head(c)
            if h == "purpose":
                m.purpose, m.purpose_node = c.items[1].value, c
            elif h == "export":
                m.export_nodes = list(c.items[1:])
            elif h == "type":
                nm = declaration_name(c).value
                path = f"{m.name}/{nm}"
                if self._reserved_cap(m, nm, c.items[1], path):
                    continue
                t = TypeInfo(m, nm, c)
                self.declaration_params(t)
                m.types[nm] = t
                m.caps[nm] = ("type", t)
                self.prog.type_index[t.qual] = t
            elif h == "error":
                nm = c.items[1].value
                if self._reserved_cap(m, nm, c.items[1], f"{m.name}/{nm}"):
                    continue
                e = ErrInfo(m, nm, c)
                m.errors[nm] = e
                m.caps[nm] = ("error", e)
            elif h == "const":
                nm = c.items[1].value
                if nm in RESERVED_VALUES:
                    self.diag(m, "E-DUP-NAME", c.items[1], f"{m.name}/{nm}", f"`{nm}` is a reserved word or prelude name")
                    continue
                ci = ConstInfo(m, nm, c)
                for k in c.items[2:]:
                    ci.clauses.setdefault(head(k), []).append(k)
                if "purpose" in ci.clauses:
                    ci.purpose = ci.clauses["purpose"][0].items[1].value
                    self._purpose_len(m, ci.purpose, ci.clauses["purpose"][0], f"{m.name}/{nm}/purpose")
                m.consts[nm] = ci
            elif h == "fn":
                nm = c.items[1].value
                if nm in RESERVED_VALUES:
                    self.diag(m, "E-DUP-NAME", c.items[1], f"{m.name}/{nm}", f"`{nm}` is a reserved word or prelude name")
                    continue
                m.fns[nm] = FnInfo(m, nm, c)

    # ---- function signatures --------------------------------------------------------------
    def _sigs(self, m: ModInfo):
        mp = m.name
        if m.purpose is None:
            self.diag(m, "E-PURPOSE-MISSING", m.root, mp, "module needs a (purpose \"...\") clause")
        else:
            self._purpose_len(m, m.purpose, m.purpose_node, mp)
        for c in m.consts.values():
            if "type" in c.clauses and len(c.clauses["type"][0].items) == 2:
                c.declared_type = self.resolve_type(m, c.clauses["type"][0].items[1], None, f"{m.name}/{c.name}/type")
        for f in m.fns.values():
            self._sig(m, f)

    def _exports(self, m: ModInfo):
        if m.export_nodes is None:
            m.exported_fns, m.exported_consts, m.exported_caps = set(m.fns), set(m.consts), set(m.types) | set(m.errors)
            return
        mp = m.name
        for i, ex in enumerate(m.export_nodes, 1):
            nm = ex.value
            if ex.kind == "sym":
                if nm in m.fns:
                    m.exported_fns.add(nm)
                elif nm in m.consts:
                    m.exported_consts.add(nm)
                else:
                    cands = sorted(list(m.fns) + list(m.consts))
                    self.diag(m, "E-NAME-UNRESOLVED", ex, f"{mp}/export", f"export `{nm}`: no such function or constant", expected=" ".join(cands), found=nm)
            elif nm in m.types or nm in m.errors:
                m.exported_caps.add(nm)
            else:
                # Exports precede variant-table construction; inspect the sum declarations.
                parent = next((t.name for t in m.types.values() if head(t.node.items[2]) == "sum"
                               and any((v.value if isinstance(v, Atom) else head(v)) == nm
                                       for v in t.node.items[2].items[1:])), None)
                if parent:
                    path = f"{mp}/export/{i}"
                    fix = [] if any(a.value == parent for a in m.export_nodes) else [
                        {"op": "replace-ref", "path": path, "to": parent}]
                    self.diag(m, "E-NAME-UNRESOLVED", ex, path,
                              f"export `{nm}`: a variant of `{parent}`; export `{parent}` (exports its variants)",
                              expected=parent, found=nm, fix=fix)
                    continue
                self.diag(m, "E-NAME-UNRESOLVED", ex, f"{mp}/export", f"export `{nm}`: no such type or error", found=nm)

    def _purpose_len(self, m, text, node, path):
        if "\n" in text or len(text) > 100:
            self.diag(m, "E-PURPOSE-LONG", node, path, "purpose must be one line of at most 100 characters", expected="<= 100", found=str(len(text)))

    def _sig(self, m: ModInfo, f: FnInfo):
        fp = f"{m.name}/{f.name}"
        counts: dict = {}
        for k in f.node.items[2:]:
            h = head(k)
            f.clauses.setdefault(h, []).append(k)
            counts[h] = counts.get(h, 0) + 1
        if "purpose" not in f.clauses:
            self.diag(m, "E-PURPOSE-MISSING", f.node, fp, f"fn `{f.name}` needs a (purpose \"...\") clause")
        else:
            f.purpose = f.clauses["purpose"][0].items[1].value
            self._purpose_len(m, f.purpose, f.clauses["purpose"][0], fp + "/purpose")
        for need in ("sig", "body"):
            if need not in f.clauses:
                self.diag(m, "E-PARSE", f.node, fp, f"fn `{f.name}` is missing its ({need} ...) clause")
        if "body" in f.clauses and len(f.clauses["body"][0].items) != 2:
            self.diag(m, "E-PARSE", f.clauses["body"][0], fp + "/body", "(body expr) takes exactly one expression")
        if "eff" in f.clauses:
            effs = set()
            for a in f.clauses["eff"][0].items[1:]:
                if a.value in EFFECTS:
                    effs.add(a.value)
                else:
                    self.diag(m, "E-NAME-UNRESOLVED", a, fp + "/eff", f"unknown effect `{a.value}`", expected=" ".join(sorted(EFFECTS)), found=a.value)
            f.eff = frozenset(effs)
        if "fails" in f.clauses:
            ids = set()
            for i, a in enumerate(f.clauses["fails"][0].items[1:], 1):
                hit = self.find_cap(m, a.value, ("error",), a, f"{fp}/fails/{i}") if a.kind == "type" else None
                if a.kind != "type":
                    self.diag(m, "E-NAME-UNRESOLVED", a, f"{fp}/fails/{i}", f"`{a.value}` is not an error name")
                if hit:
                    ids.add(hit[1].id)
                    self.prog.refs[(m.name, f"{fp}/fails/{i}")] = hit[1].id
            f.fails = frozenset(ids)
        if "sig" not in f.clauses:
            return
        sig = f.clauses["sig"][0]
        items = sig.items[1:]
        arrow = [i for i, x in enumerate(items) if isinstance(x, Atom) and x.value == "->"]
        if len(arrow) != 1 or arrow[0] != len(items) - 2:
            self.diag(m, "E-PARSE", sig, fp + "/sig", "sig must be (sig (param Type)... -> ReturnType)")
            return
        tv: set = set()
        seen = set()
        for i, p in enumerate(items[:-2], 1):
            pp = f"{fp}/sig/{i}"
            if not (isinstance(p, SList) and len(p.items) == 2 and isinstance(p.items[0], Atom) and p.items[0].kind == "sym"
                    and FN_NAME.fullmatch(p.items[0].value)):
                self.diag(m, "E-PARSE", p, pp, "parameter must be (name Type)")
                return
            nm = p.items[0].value
            if nm in RESERVED_VALUES or nm in m.fns or nm in seen:
                self.diag(m, "E-DUP-NAME", p.items[0], pp, self._local_collision(m, nm, seen))
            seen.add(nm)
            f.params.append((nm, self.resolve_type(m, p.items[1], tv, pp + "/1")))
        f.ret = self.resolve_type(m, items[-1], tv, f"{fp}/sig/{len(items)}")
        f.sig_ok = True

    def fn_type(self, f: FnInfo, mapping=None):
        return self.s.inst(fn([t for _, t in f.params], f.ret), {} if mapping is None else mapping)

    def _local_collision(self, m, name, env):
        if name == "result":
            return "`result` is reserved (bound to the return value in `ensures`); rename it, e.g. `res`"
        reason = ("a reserved word" if name in RESERVED_VALUES else
                  "a function of this module" if name in m.fns else
                  "a constant of this module" if name in m.consts else
                  "a binding already in scope" if name in env else
                  "a binding already introduced here")
        hint = "; `pair` is the prelude pair constructor, name it `p` instead" if name == "pair" else ""
        return f"`{name}` collides with {reason}{hint}"

    # ---- lookups ----------------------------------------------------------------------------
    def find_module(self, m, q, node, path, near=None):
        if q == m.name:
            self.diag(m, "E-NAME-UNRESOLVED", node, path, f"refer to names of module `{q}` unqualified inside it", found=q, near=near)
            return None
        if q in {u.value for u in m.uses}:
            m2 = self.prog.modules.get(q)
            if m2:
                m.used.add(q)
            return m2
        if q in self.prog.available:
            self.diag(m, "E-USE-MISSING", node, path, f"module `{q}` is not in (use ...)", expected=f"(use {q})", found=q,
                      fix=[{"op": "add-use", "module": m.name, "use": q}], near=near)
        else:
            self.diag(m, "E-NAME-UNRESOLVED", node, path, f"no module named `{q}`", expected=" ".join(suggest(q, self.prog.available)), found=q, near=near)
        return None

    def find_fn(self, m, name, node, path):
        """Qualified function lookup. Returns FnInfo or None (diagnosed)."""
        q, base = name.split(".", 1)
        m2 = self.find_module(m, q, node, path)
        if m2 is None:
            return None
        f = m2.fns.get(base)
        if f is None:
            cands = [f"{q}.{n}" for n in sorted(m2.exported_fns)]
            self.diag(m, "E-NAME-UNRESOLVED", node, path, f"module `{q}` has no function `{base}`", expected=" ".join(suggest(name, cands) or cands[:8]),
                      found=name, fix=self._ref_fix(path, name, cands))
            return None
        if base not in m2.exported_fns:
            self.diag(m, "E-NOT-EXPORTED", node, path, f"`{name}` exists but module `{q}` does not export it", found=name)
            return None
        if m.name != m2.name:
            m2.referenced_fns.add(base)
        return f

    def _ref_fix(self, path, name, cands):
        s = suggest(name, cands, 1)
        return [{"op": "replace-ref", "path": path, "to": s[0]}] if s else []

    def find_cap(self, m, name, kinds, node, path):
        """Capitalized name -> (kind, info) or None (diagnosed)."""
        if "." in name:
            q, base = name.split(".", 1)
            m2 = self.find_module(m, q, node, path)
            if m2 is None:
                return None
            hit = m2.caps.get(base)
            if hit is not None and base not in m2.exported_caps:
                self.diag(m, "E-NOT-EXPORTED", node, path, f"`{name}` exists but module `{q}` does not export it", found=name)
                return None
            cands = [f"{q}.{n}" for n in sorted(m2.exported_caps)]
        else:
            hit = m.caps.get(name) or self.prelude.caps.get(name)
            cands = sorted(set(m.caps) | set(self.prelude.caps) | set(BASE))
        if hit is None:
            self.diag(m, "E-NAME-UNRESOLVED", node, path, f"unknown name `{name}`", expected=" ".join(suggest(name, cands) or cands[:8]), found=name,
                      fix=self._ref_fix(path, name, cands))
            return None
        if hit[0] not in kinds:
            self.diag(m, "E-TYPE", node, path, f"`{name}` is a {hit[0]}, expected {' or '.join(kinds)}", expected="/".join(kinds), found=hit[0])
            return None
        return hit
