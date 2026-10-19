"""Sum-type variant rename (ADR-058 item 6): definitions, constructors, patterns, scenarios."""
from __future__ import annotations

from pathlib import Path

from .ast import TYPE_NAME_RE
from .edit import EditError, get_at, locate, set_at, _swap_export
from .prelude import RESERVED_CAPS
from .resolve import head
from .sexpr import Atom, SList, read


def check_spelling(a0: str) -> str | None:
    """Return error message if a0 has mod.Type.Variant or Type.Variant spelling, else None."""
    if a0.count(".") == 2:
        m, _, v = a0.split(".", 2)
        return f"write '{m}.{v}' instead of '{a0}'"
    if a0.count(".") == 1:
        p0, p1 = a0.split(".", 1)
        if p0[:1].isupper() and p1[:1].isupper():
            return f"write 'mod.{p1}' instead of '{a0}'"
    return None


def _find_variant_atoms(node, target: str) -> list[Atom]:
    atoms = []

    def walk(n):
        if isinstance(n, Atom):
            if n.kind != "str" and n.value == target:
                atoms.append(n)
        elif isinstance(n, SList):
            for item in n.items:
                walk(item)

    walk(node)
    return atoms


def _check_and_update_scenarios(w, q: str, new_q: str, force: bool):
    accept_dir = Path("tests/accept")
    if not accept_dir.is_dir() and w.roots:
        mfile = Path(w.prog.modules[next(iter(w.roots))].file)
        cand = (mfile.parent.parent if mfile.parent.name in ("src", "examples") else mfile.parent) / "tests/accept"
        if cand.is_dir():
            accept_dir = cand
    if not accept_dir.is_dir():
        return

    touched_by_file: dict[Path, list] = {}
    for fpath in sorted(accept_dir.rglob("*.accept")):
        text = fpath.read_text(encoding="utf-8")
        node, _ = read(text, str(fpath))
        if node is None or not (isinstance(node, SList) and node.items and getattr(node.items[0], "value", None) == "scenarios"):
            continue
        for sc in node.items[1:]:
            if not (isinstance(sc, SList) and len(sc.items) >= 2 and getattr(sc.items[0], "value", None) == "scenario"):
                continue
            sc_name = sc.items[1].value if isinstance(sc.items[1], Atom) and sc.items[1].kind == "str" else "<unknown>"
            status = None
            status_atom = None
            run_clause = None
            exp_clause = None
            for c in sc.items[2:]:
                if isinstance(c, SList) and c.items and isinstance(c.items[0], Atom):
                    h = c.items[0].value
                    if h == "status" and len(c.items) == 2 and isinstance(c.items[1], Atom):
                        status = c.items[1].value
                        status_atom = c.items[1]
                    elif h == "run" and len(c.items) >= 2:
                        run_clause = c
                    elif h in ("expect", "expect-fail") and len(c.items) >= 2:
                        exp_clause = c
            atoms = []
            if run_clause is not None:
                for arg in run_clause.items[2:]:
                    atoms.extend(_find_variant_atoms(arg, q))
            if exp_clause is not None:
                for ex_item in exp_clause.items[1:]:
                    atoms.extend(_find_variant_atoms(ex_item, q))
            if atoms:
                touched_by_file.setdefault(fpath, []).append((sc_name, atoms, status, status_atom))

    if not touched_by_file:
        return

    all_sc_names = sorted({sc_name for group in touched_by_file.values() for sc_name, _, _, _ in group})
    if not force:
        raise EditError(f"{q} is referenced by scenario(s): {', '.join(all_sc_names)} (use --force to update)")

    for fpath, group in touched_by_file.items():
        text = fpath.read_text(encoding="utf-8")
        lines = text.splitlines(keepends=True)
        replacements = []
        for sc_name, atoms, status, status_atom in group:
            for a in atoms:
                replacements.append((a.line, a.col, len(q), new_q))
            if status == "approved" and status_atom is not None:
                replacements.append((status_atom.line, status_atom.col, len("approved"), "proposed"))
        replacements.sort(key=lambda r: (r[0], -r[1]))
        for l_num, c_num, old_len, repl in replacements:
            idx_l = l_num - 1
            idx_c = c_num - 1
            lines[idx_l] = lines[idx_l][:idx_c] + repl + lines[idx_l][idx_c + old_len:]
        w.scenario_olds[fpath] = text
        w.scenario_news[fpath] = "".join(lines)


def rename_variant(w, s, new_name: str, force: bool = False):
    old = s.name
    new = new_name
    mn = s.mod.name
    if new.startswith(mn + "."):
        new = new[len(mn) + 1:]
    if not TYPE_NAME_RE.fullmatch(new):
        raise EditError(f"`{new}` is not a valid Capitalized name")
    if new != old and (new in s.mod.caps or new in RESERVED_CAPS):
        raise EditError(f"`{new}` collides with an existing type, variant, or error in module {mn}")

    q = s.qual
    new_q = f"{mn}.{new}"

    _check_and_update_scenarios(w, q, new_q, force)

    roots = dict(w.roots)
    own = roots[mn]
    tname = s.info.tname
    di = locate(own, [mn, tname])[0]
    decl = own.items[di]

    sum_idx = next(i for i, c in enumerate(decl.items) if i >= 2 and head(c) == "sum")
    sum_clause = decl.items[sum_idx]

    new_items = []
    for v in sum_clause.items[1:]:
        if isinstance(v, Atom) and v.value == old:
            new_items.append(Atom(v.kind, new, v.line, v.col))
        elif isinstance(v, SList) and v.items and isinstance(v.items[0], Atom) and v.items[0].value == old:
            new_h = Atom(v.items[0].kind, new, v.items[0].line, v.items[0].col)
            new_items.append(SList((new_h,) + v.items[1:], v.line, v.col))
        else:
            new_items.append(v)

    new_sum = SList((sum_clause.items[0],) + tuple(new_items), sum_clause.line, sum_clause.col)
    decl_items = list(decl.items)
    decl_items[sum_idx] = new_sum
    own = set_at(own, [di], SList(tuple(decl_items), decl.line, decl.col))
    own = SList(tuple(_swap_export(c, old, new) if head(c) == "export" else c for c in own.items))
    roots[mn] = own
    w.changed.add(mn)

    def swap(atom):
        if atom.value == old:
            return Atom(atom.kind, new)
        if atom.value == q:
            return Atom(atom.kind, new_q)
        return None

    for (ref_mn, path), target in sorted(w.prog.refs.items()):
        if target != q or ref_mn not in roots:
            continue
        idxs = locate(roots[ref_mn], path.split("/"))
        node = get_at(roots[ref_mn], idxs)
        if isinstance(node, Atom):
            r = swap(node)
            if r is not None:
                roots[ref_mn] = set_at(roots[ref_mn], idxs, r)
                w.changed.add(ref_mn)
        elif isinstance(node, SList) and node.items and isinstance(node.items[0], Atom):
            r = swap(node.items[0])
            if r is not None:
                new_slist = SList((r,) + node.items[1:], node.line, node.col)
                roots[ref_mn] = set_at(roots[ref_mn], idxs, new_slist)
                w.changed.add(ref_mn)

    for mname in sorted(w.changed):
        w.put(mname, roots[mname])
