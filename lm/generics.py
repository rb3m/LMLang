"""Generic declaration scopes, type expressions, and regular recursion checks."""
from __future__ import annotations

import re

from .program import ModInfo, TypeInfo, VariantInfo
from .sexpr import Atom, SList
from .types import (
    BASE, KEY, fn, keys_of, lst, mapt, nom, opt, pair, sett, substitute,
    var, vec,
)

FN_NAME = re.compile(r"[a-z][a-z0-9-]*")
TVAR = re.compile(r"[a-z]")


def head(node):
    if isinstance(node, SList) and node.items and isinstance(node.items[0], Atom):
        return node.items[0].value
    return None


def declaration_name(node):
    name = node.items[1]
    return name.items[0] if isinstance(name, SList) else name


class GenericMixin:
    def _fields(self, m, nodes, path, first, tvars=None):
        """Use parent-relative `first` to retain addressable field paths."""
        out, seen = [], set()
        for i, f in enumerate(nodes, first):
            if not (isinstance(f, SList) and len(f.items) == 2
                    and isinstance(f.items[0], Atom)
                    and f.items[0].kind == "sym"
                    and FN_NAME.fullmatch(f.items[0].value)):
                self.diag(m, "E-PARSE", f, f"{path}/{i}", "field must be (name Type)")
                continue
            nm = f.items[0].value
            if nm in seen:
                self.diag(m, "E-DUP-NAME", f, f"{path}/{i}", f"duplicate field `{nm}`")
                continue
            seen.add(nm)
            out.append((nm, self.resolve_type(m, f.items[1], tvars, f"{path}/{i}/1")))
        return out

    def _decls(self, m: ModInfo):
        for e in m.errors.values():
            e.fields = self._fields(m, e.node.items[2:], f"{m.name}/{e.name}", 2)
        for t in m.types.values():
            body = t.node.items[2:]
            path = f"{m.name}/{t.name}"
            if len(body) != 1:
                self.diag(m, "E-PARSE", t.node, path,
                          "(type Name T) takes exactly one type or (rec ..)/(sum ..)")
                t.alias_t = self.s.fresh()
                continue
            b = body[0]
            if head(b) == "rec":
                t.kind = "rec"
                t.fields = self._fields(m, b.items[1:], path + "/2", 1, frozenset(t.params))
            elif head(b) == "sum":
                t.kind = "sum"
                for i, v in enumerate(b.items[1:], 1):
                    vp = f"{path}/2/{i}"
                    vnode = v.items[0] if isinstance(v, SList) and v.items else v
                    if not (isinstance(vnode, Atom) and vnode.kind == "type"
                            and "." not in vnode.value):
                        self.diag(m, "E-PARSE", v, vp,
                                  "variant must be Name or (Name (field Type)...)")
                        continue
                    if self._reserved_cap(m, vnode.value, vnode, vp):
                        continue
                    flds = []
                    if isinstance(v, SList):
                        flds = self._fields(m, v.items[1:], vp, 1, frozenset(t.params))
                    instance = nom(t.qual, *(var(p) for p in t.params))
                    vi = VariantInfo(m, vnode.value, t.name, flds, instance)
                    t.variants[vi.name] = vi
                    m.variants[vi.name] = vi
                    m.caps[vi.name] = ("variant", vi)
                    if t.name in m.exported_caps:
                        m.exported_caps.add(vi.name)
            else:
                t.alias_node = b
        for t in m.types.values():
            if t.kind == "alias" and t.alias_node is not None:
                self.alias_type(t)

    def alias_type(self, t: TypeInfo):
        if t.alias_t is not None:
            return t.alias_t
        if t.busy:
            self.diag(t.mod, "E-CYCLE", t.node, f"{t.mod.name}/{t.name}",
                      f"type alias `{t.name}` refers to itself")
            return self.s.fresh()
        t.busy = True
        t.alias_t = self.resolve_type(t.mod, t.alias_node, frozenset(t.params),
                                      f"{t.mod.name}/{t.name}/2")
        t.busy = False
        return t.alias_t

    # ---- type expressions ----------------------------------------------------------------
    def resolve_type(self, m, n, tvars, path):
        """tvars: None = type variables not allowed; a set = collect used variable names."""
        def bad(msg):
            self.diag(m, "E-TYPE", n, path, msg)
            return self.s.fresh()

        if isinstance(n, Atom):
            if n.kind == "type":
                v = n.value
                if v in BASE:
                    return BASE[v]
                if v in ("List", "Vec", "Opt", "Pair", "Map", "Set", "Fn"):
                    return bad(f"`{v}` needs arguments")
                hit = self.find_cap(m, v, ("type",), n, path)
                if hit is None:
                    return self.s.fresh()
                self.prog.refs[(m.name, path)] = hit[1].qual
                return self.applied_type(m, hit[1], [], n, path)
            if n.kind == "sym" and TVAR.fullmatch(n.value):
                if tvars is None:
                    return bad(f"type variable `{n.value}` needs a declaration "
                               "or function signature scope")
                if isinstance(tvars, frozenset):
                    if n.value not in tvars:
                        return bad(f"undeclared type variable `{n.value}`")
                else:
                    tvars.add(n.value)
                return var(n.value)
            return bad("expected a type")
        h = head(n)
        if h in ("List", "Vec", "Opt") and len(n.items) == 2:
            inner = self.resolve_type(m, n.items[1], tvars, path + "/1")
            return {"List": lst, "Vec": vec, "Opt": opt}[h](inner)
        if h == "Pair" and len(n.items) == 3:
            return pair(self.resolve_type(m, n.items[1], tvars, path + "/1"),
                        self.resolve_type(m, n.items[2], tvars, path + "/2"))
        if (h, len(n.items)) in (("Map", 3), ("Set", 2)):
            k = self.key_type(m, n.items[1], tvars, path + "/1")
            if h == "Set":
                return sett(k)
            return mapt(k, self.resolve_type(m, n.items[2], tvars, path + "/2"))
        if h == "Fn" and len(n.items) == 3 and isinstance(n.items[1], SList):
            args = [self.resolve_type(m, a, tvars, f"{path}/1/{i}")
                    for i, a in enumerate(n.items[1].items)]
            return fn(args, self.resolve_type(m, n.items[2], tvars, path + "/2"))
        if n.items and isinstance(n.items[0], Atom) and n.items[0].kind == "type":
            name = n.items[0]
            if h not in (*BASE, "List", "Vec", "Opt", "Pair", "Map", "Set", "Fn"):
                hit = self.find_cap(m, h, ("type",), name, path + "/0")
                if hit is None:
                    return self.s.fresh()
                self.prog.refs[(m.name, path + "/0")] = hit[1].qual
                if not hit[1].params:
                    return bad(f"`{h}` is not a generic type")
                args = [self.resolve_type(m, a, tvars, f"{path}/{i}")
                        for i, a in enumerate(n.items[1:], 1)]
                return self.applied_type(m, hit[1], args, n, path)
        return bad("malformed type; use Int Float Bool Str Unit (List T) (Vec T) "
                   "(Opt T) (Pair A B) (Map K V) (Set K) (Fn (T..) R) "
                   "or a declared type")

    def key_type(self, m, n, tvars, path):
        """A Map key / Set element type: Int, Float, Str, Bool, or a signature type variable, whose
        instances are checked at every use (ADR-049 item 1, ADR-050)."""
        t = self.resolve_type(m, n, tvars, path)
        wt = self.s.walk(t)
        if wt[0] not in (*KEY, "V", "M"):
            shown = self.s.show(t)
            hint = "; suggest a Str key or nested maps" if wt[0] == "Pair" else ""
            self.diag(m, "E-TYPE", n, path,
                      f"Map keys and Set elements must be Int, Float, Str or Bool, "
                      f"found {shown}{hint}",
                      expected="Int, Float, Str or Bool", found=shown)
        return t

    def applied_type(self, m, info, args, node, path):
        if len(args) != len(info.params):
            self.diag(m, "E-TYPE", node, path,
                      f"`{info.name}` needs {len(info.params)} type arguments, found {len(args)}")
            return self.s.fresh()
        if info.kind == "alias":
            return substitute(self.alias_type(info), dict(zip(info.params, args)))
        return nom(info.qual, *args)

    def declaration_params(self, info):
        name = info.node.items[1]
        if not isinstance(name, SList):
            return
        path = f"{info.mod.name}/{info.name}/1"
        seen = set()
        for p in name.items[1:]:
            if not (isinstance(p, Atom) and p.kind == "sym" and TVAR.fullmatch(p.value)):
                self.diag(info.mod, "E-TYPE", p, path,
                          "type parameters must be single lowercase letters")
                continue
            if p.value in seen:
                self.diag(info.mod, "E-TYPE", p, path, f"duplicate type parameter `{p.value}`")
            seen.add(p.value)
        info.params = tuple(dict.fromkeys(p.value for p in name.items[1:]
                                         if isinstance(p, Atom) and p.value in seen))
        if not name.items[1:]:
            self.diag(info.mod, "E-TYPE", name, path, "generic declaration needs type parameters")
        used = set()

        def visit_type(node):
            if isinstance(node, Atom):
                if node.kind == "sym":
                    used.add(node.value)
                return
            for child in node.items:
                visit_type(child)

        def visit_fields(fields):
            for field in fields:
                if isinstance(field, SList) and len(field.items) == 2:
                    visit_type(field.items[1])

        for body in info.node.items[2:]:
            if head(body) == "rec":
                visit_fields(body.items[1:])
            elif head(body) == "sum":
                for variant in body.items[1:]:
                    if isinstance(variant, SList):
                        visit_fields(variant.items[1:])
            else:
                visit_type(body)
        for p in info.params:
            if p not in used:
                self.diag(info.mod, "E-TYPE", name, path, f"unused type parameter `{p}`")

    def classify_types(self, m):
        # Classify all declarations before resolving forward references.
        for t in m.types.values():
            body = t.node.items[2:]
            if len(body) != 1:
                continue
            if head(body[0]) in ("rec", "sum"):
                t.kind = head(body[0])
                continue
            t.alias_node = body[0]

    def check_declared_keys(self):
        """Check instantiated generic fields after all declarations are available."""
        for m in self.prog.modules.values():
            entries = []
            for t in m.types.values():
                fields = t.fields + [f for v in t.variants.values() for f in v.fields]
                entries += [(ty, t.node, f"{m.name}/{t.name}") for _, ty in fields]
                if t.alias_t is not None:
                    entries.append((t.alias_t, t.node, f"{m.name}/{t.name}"))
            for e in m.errors.values():
                entries += [(ty, e.node, f"{m.name}/{e.name}") for _, ty in e.fields]
            for f in m.fns.values():
                entries += [(ty, f.node, f"{m.name}/{f.name}/sig")
                            for _, ty in f.params]
                if f.ret is not None:
                    entries.append((f.ret, f.node, f"{m.name}/{f.name}/sig"))
            for c in m.consts.values():
                if c.declared_type is not None:
                    entries.append((c.declared_type, c.node, f"{m.name}/{c.name}/type"))
            for ty, node, path in entries:
                for key in keys_of(ty, self.prog.type_index):
                    if self.s.walk(key)[0] not in (*KEY, "V", "M"):
                        hint = ""
                        if self.s.walk(key)[0] == "Pair":
                            hint = "; suggest a Str key or nested maps"
                        self.diag(m, "E-TYPE", node, path,
                                  "Map keys and Set elements must be "
                                  "Int, Float, Str or Bool" + hint,
                                  found=self.s.show(key))

    def check_regular_recursion(self):
        from .generic_cycles import check_regular_recursion
        check_regular_recursion(self)
