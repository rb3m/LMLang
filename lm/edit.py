"""Edit-by-operation: change canonical ASTs, reprint canonically, never regenerate whole files."""
from __future__ import annotations

import json
import re

from .ast import FN_ORDER, NAME_RE, TYPE_NAME_RE, canonicalize
from .generics import declaration_name
from .printer import print_module
from .resolve import head
from .sexpr import Atom, SList, classify, read, to_data


class EditError(Exception):
    def __init__(self, msg, diags=()):
        super().__init__(msg)
        self.diags = list(diags)


# ---- path addressing (node paths from diagnostics -> index lists) ---------------------------------
def _clause_idx(decl, seg):
    h, _, k = seg.partition("#")
    want, n = int(k or 0), 0
    for i, c in enumerate(decl.items):
        if i >= 2 and head(c) == h:
            if n == want:
                return i
            n += 1
    raise EditError(f"no clause `{seg}`")


def locate(root, segs):
    """segs = path.split('/'); returns indices from the module root."""
    if len(segs) == 1:
        return []
    out = []
    first = segs[1]
    for i, c in enumerate(root.items):
        is_decl = (head(c) in ("fn", "type", "error", "const")
                   and declaration_name(c).value == first)
        is_clause = head(c) == first and first in ("purpose", "use", "export")
        if i >= 2 and (is_decl or is_clause):
            out.append(i)
            decl = c
            break
    else:
        raise EditError(f"no declaration `{first}` in module {segs[0]}")
    rest = segs[2:]
    if head(decl) in ("fn", "const") and rest:
        j = _clause_idx(decl, rest[0])
        out.append(j)
        rest = rest[1:]
    return out + [int(s) for s in rest]


def get_at(node, idxs):
    for i in idxs:
        node = node.items[i]
    return node


def set_at(node, idxs, new):
    if not idxs:
        return new
    i = idxs[0]
    return SList(node.items[:i] + (set_at(node.items[i], idxs[1:], new),) + node.items[i + 1:], node.line, node.col)


def sym(v):
    return Atom("sym", v)


def parse_one(text, what):
    n, d = read(text, "<arg>")
    if n is None:
        raise EditError(f"cannot parse {what}: {d[0].msg} (line {d[0].line}, col {d[0].col})", d)
    return n


def parse_form(text, h):
    n = parse_one(text, f"({h} ...)")
    if head(n) != h:
        raise EditError(f"expected a ({h} ...) form")
    return n


# ---- the working set --------------------------------------------------------------------------------
class Work:
    def __init__(self, prog, idx):
        self.prog, self.idx = prog, idx
        self.roots = {n: m.root for n, m in prog.modules.items() if m.is_target}
        self.changed: set = set()
        self.scenario_news: dict = {}
        self.scenario_olds: dict = {}

    def mod(self, name):
        if name not in self.roots:
            raise EditError(f"module `{name}` is not part of this project")
        return self.prog.modules[name]

    def put(self, name, root):
        m = self.mod(name)
        canon, diags = canonicalize(root, m.file)
        if canon is None:
            raise EditError(f"edit would produce an invalid module: {diags[0].msg}", diags)
        self.roots[name] = canon
        self.changed.add(name)

    def symbol(self, text, kinds=("fn", "type", "error", "const", "variant")):
        if "." in text:
            mn, nm = text.split(".", 1)
            m = self.prog.modules.get(mn)
            if m and nm in m.variants:
                self.mod(mn)
                from .index import Symbol
                return Symbol("variant", m, nm, m.variants[nm])
        s, err = self.idx.find(text)
        if s is None:
            raise EditError(err)
        if s.kind not in kinds:
            raise EditError(f"`{text}` is a {s.kind}; this operation needs {' or '.join(kinds)}")
        self.mod(s.mod.name)
        return s

    def decl_idx(self, s):
        return locate(self.roots[s.mod.name], [s.mod.name, s.name])[0]


# ---- operations -----------------------------------------------------------------------------------------
def replace_body(w, a):
    s = w.symbol(a[0], ("fn",))
    root = w.roots[s.mod.name]
    w.put(s.mod.name, set_at(root, locate(root, [s.mod.name, s.name, "body", "1"]), parse_one(a[1], "expression")))


def replace_decl(w, a):
    s = w.symbol(a[0])
    form = parse_form(a[1], s.kind)
    name = form.items[1] if len(form.items) > 1 else None
    if isinstance(name, SList):
        name = name.items[0] if name.items else None
    if not isinstance(name, Atom) or name.value != s.name:
        raise EditError(f"the new form must keep the name `{s.name}` (use rename to change it)")
    root = w.roots[s.mod.name]
    w.put(s.mod.name, set_at(root, [w.decl_idx(s)], form))


def add_decl(w, a):
    m = w.mod(a[0])
    form = parse_one(a[1], "declaration")
    if head(form) not in ("fn", "type", "error", "const"):
        raise EditError("expected a (fn ...), (type ...), (error ...) or (const ...) form")
    w.put(m.name, SList(w.roots[m.name].items + (form,)))


def remove_decl(w, a, force=False):
    s = w.symbol(a[0], ("fn", "const"))
    callers = [c for c, _ in w.idx.callers(s.qual)]
    if callers and not force:
        raise EditError(f"{s.qual} is still referenced by: {' '.join(sorted(set(callers)))} (use --force to remove anyway)")
    root = w.roots[s.mod.name]
    items = list(root.items)
    del items[w.decl_idx(s)]
    items = [_without(c, s.name) if head(c) == "export" else c for c in items]
    w.put(s.mod.name, SList(tuple(items)))


remove_fn = remove_decl


def _without(clause, name):
    return SList(tuple(x for x in clause.items if not (isinstance(x, Atom) and x.value == name)))


def set_purpose(w, a):
    target, text = a[0], a[1]
    if "." in target:
        s = w.symbol(target, ("fn",))
        mn, decl_idx = s.mod.name, w.decl_idx(s)
        root = w.roots[mn]
        d = root.items[decl_idx]
        d = SList(tuple(c for c in d.items if head(c) != "purpose") + (SList((sym("purpose"), Atom("str", text))),))
        w.put(mn, set_at(root, [decl_idx], d))
    else:
        root = w.roots[w.mod(target).name]
        kept = tuple(c for c in root.items if head(c) != "purpose")
        w.put(target, SList(kept + (SList((sym("purpose"), Atom("str", text))),)))


def set_sig(w, a):
    s = w.symbol(a[0], ("fn",))
    root = w.roots[s.mod.name]
    d = root.items[w.decl_idx(s)]
    d = SList(tuple(c for c in d.items if head(c) != "sig") + (parse_form(a[1], "sig"),))
    w.put(s.mod.name, set_at(root, [w.decl_idx(s)], d))


def _list_clause(w, mn, h, name, add, node_kind="sym"):
    root = w.roots[w.mod(mn).name]
    items = list(root.items)
    k = next((i for i, c in enumerate(items) if i >= 2 and head(c) == h), None)
    if k is None:
        if not add:
            return
        items.append(SList((sym(h), Atom(node_kind, name))))
    else:
        present = any(isinstance(x, Atom) and x.value == name for x in items[k].items[1:])
        if present == add:
            return
        items[k] = SList(items[k].items + (Atom(node_kind, name),)) if add else _without(items[k], name)
    w.put(mn, SList(tuple(items)))


def add_use(w, a):
    _list_clause(w, a[0], "use", a[1], True)


def remove_use(w, a):
    _list_clause(w, a[0], "use", a[1], False)


def add_export(w, a):
    m = w.mod(a[0])
    root = w.roots[m.name]
    if not any(i >= 2 and head(c) == "export" for i, c in enumerate(root.items)):
        raise EditError(f"module `{m.name}` has no export clause (everything is already exported)")
    _list_clause(w, a[0], "export", a[1], True, "type" if a[1][:1].isupper() else "sym")


def _fn_list(w, a, h, kind):
    s = w.symbol(a[0], ("fn",))
    root = w.roots[s.mod.name]
    di = w.decl_idx(s)
    d = root.items[di]
    items = list(d.items)
    k = next((i for i, c in enumerate(items) if i >= 2 and head(c) == h), None)
    atom = Atom(kind, a[1])
    if k is None:
        items.append(SList((sym(h), atom)))
    elif not any(x.value == a[1] for x in items[k].items[1:] if isinstance(x, Atom)):
        items[k] = SList(items[k].items + (atom,))
    w.put(s.mod.name, set_at(root, [di], SList(tuple(items))))


def add_eff(w, a):
    _fn_list(w, a, "eff", "sym")


def add_fails(w, a):
    _fn_list(w, a, "fails", "type")


def add_example(w, a):
    s = w.symbol(a[0], ("fn",))
    root = w.roots[s.mod.name]
    di = w.decl_idx(s)
    d = root.items[di]
    w.put(s.mod.name, set_at(root, [di], SList(d.items + (parse_form(a[1], "example"),))))


def replace_ref(w, a):
    path, to = a[0], a[1]
    mn = path.split("/")[0]
    root = w.roots[w.mod(mn).name]
    idxs = locate(root, path.split("/"))
    old = get_at(root, idxs)
    if not isinstance(old, Atom):
        raise EditError(f"path {path} does not address a name")
    new = classify(to, 0, 0)
    if new is None or new.kind not in ("sym", "type"):
        raise EditError(f"`{to}` is not a valid name")
    w.put(mn, set_at(root, idxs, new))


def rename(w, a, force=False):
    s = w.symbol(a[0])
    if s.kind == "variant":
        from .edit_variant import rename_variant
        rename_variant(w, s, a[1], force)
        return
    old, new = s.name, a[1]
    if new.startswith(s.mod.name + "."):
        new = new[len(s.mod.name) + 1:]
    if not (NAME_RE if s.kind in ("fn", "const") else TYPE_NAME_RE).fullmatch(new):
        raise EditError(f"`{new}` is not a valid {'lowercase-kebab' if s.kind in ('fn', 'const') else 'Capitalized'} name")
    q = s.qual

    def swap(atom):
        if atom.value == old:
            return Atom(atom.kind, new)
        if atom.value == f"{s.mod.name}.{old}":
            return Atom(atom.kind, f"{s.mod.name}.{new}")
        return None

    roots = dict(w.roots)
    for (mn, path), target in sorted(w.prog.refs.items()):
        if target != q or mn not in roots:
            continue
        idxs = locate(roots[mn], path.split("/"))
        node = get_at(roots[mn], idxs)
        r = swap(node) if isinstance(node, Atom) else None
        if r is not None:
            roots[mn] = set_at(roots[mn], idxs, r)
            w.changed.add(mn)
    own = roots[s.mod.name]
    di = locate(own, [s.mod.name, old])[0]
    name_path = [di, 1]
    if isinstance(own.items[di].items[1], SList):
        name_path.append(0)
    own = set_at(own, name_path, Atom(declaration_name(own.items[di]).kind, new))
    own = SList(tuple(_swap_export(c, old, new) if head(c) == "export" else c for c in own.items))
    roots[s.mod.name] = own
    w.changed.add(s.mod.name)
    for mn in sorted(w.changed):
        w.put(mn, roots[mn])


def _swap_export(c, old, new):
    return SList(tuple(Atom(x.kind, new) if isinstance(x, Atom) and x.value == old and x is not c.items[0] else x for x in c.items))


OPS = {
    "replace-body": (replace_body, 2, "SYM EXPR"),
    "replace-decl": (replace_decl, 2, "SYM FORM"),
    "add-decl": (add_decl, 2, "MODULE FORM"),
    "remove-decl": (remove_decl, 1, "SYM [--force]"),
    "remove-fn": (remove_fn, 1, "SYM [--force]"),
    "rename": (rename, 2, "SYM NEWNAME"),
    "set-purpose": (set_purpose, 2, "SYM|MODULE TEXT"),
    "set-sig": (set_sig, 2, "SYM '(sig ...)'"),
    "add-use": (add_use, 2, "MODULE NAME"),
    "remove-use": (remove_use, 2, "MODULE NAME"),
    "add-export": (add_export, 2, "MODULE NAME"),
    "add-eff": (add_eff, 2, "SYM EFFECT"),
    "add-fails": (add_fails, 2, "SYM ERROR"),
    "add-example": (add_example, 2, "SYM '(example ...)'"),
    "replace-ref": (replace_ref, 2, "NODE-PATH NEWNAME"),
}


def apply_fix(w, fix):
    """Apply one machine fix object taken from a diagnostic."""
    op = fix.get("op")
    if op == "add-use":
        add_use(w, [fix["module"], fix["use"]])
    elif op == "remove-use":
        remove_use(w, [fix["module"], fix["use"]])
    elif op == "add-eff":
        add_eff(w, [fix["fn"], fix["eff"]])
    elif op == "add-fails":
        mn = fix["fn"].split(".", 1)[0]
        e = fix["error"]
        add_fails(w, [fix["fn"], e[len(mn) + 1:] if e.startswith(mn + ".") else e])
    elif op == "replace-ref":
        replace_ref(w, [fix["path"], fix["to"]])
    else:
        raise EditError(f"fix op `{op}` is not applicable here")


def apply_json(w, text):
    try:
        fixes = json.loads(text)
    except ValueError as ex:
        raise EditError(f"bad JSON: {ex}")
    for f in fixes if isinstance(fixes, list) else [fixes]:
        apply_fix(w, f)
