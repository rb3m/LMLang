"""Const dependency sorting for IR lowering."""
from __future__ import annotations

from . import ir


def find_refs(e):
    """Find all const and fn references in an IR expression tree."""
    cs, fs = set(), set()
    stack = [e]
    while stack:
        cur = stack.pop()
        if cur is None:
            continue
        if isinstance(cur, ir.ConstRef):
            cs.add(cur.cid)
        elif isinstance(cur, (ir.Call, ir.FnRef)):
            fs.add(cur.fid)
        stack.extend(ir.children(cur))
    return cs, fs


def sort_consts(out: ir.Program) -> list[str]:
    """Compute const_order as a topological order over transitive const->fn->const dependencies."""
    fn_const_deps: dict[str, set[str]] = {}
    fn_fn_deps: dict[str, set[str]] = {}
    for fid, f in out.fns.items():
        cs, fs = set(), set()
        exprs = []
        if f.body is not None:
            exprs.append(f.body)
        for req in f.requires:
            exprs.append(req.expr)
        for ens in f.ensures:
            exprs.append(ens.expr)
        for e in exprs:
            c_refs, f_refs = find_refs(e)
            cs |= c_refs
            fs |= f_refs
        fn_const_deps[fid] = cs
        fn_fn_deps[fid] = fs

    fn_trans_consts = {fid: set(cs) for fid, cs in fn_const_deps.items()}
    changed = True
    while changed:
        changed = False
        for fid, next_fids in fn_fn_deps.items():
            for nxt in next_fids:
                if nxt in fn_trans_consts:
                    before = len(fn_trans_consts[fid])
                    fn_trans_consts[fid] |= fn_trans_consts[nxt]
                    if len(fn_trans_consts[fid]) > before:
                        changed = True

    const_deps: dict[str, set[str]] = {}
    for cid, c in out.consts.items():
        cs, fs = find_refs(c.expr)
        all_cs = set(cs)
        for fid in fs:
            all_cs |= fn_trans_consts.get(fid, set())
        const_deps[cid] = (all_cs & set(out.consts)) - {cid}

    visiting, visited, order = set(), set(), []

    def dfs(cid: str):
        if cid in visited or cid in visiting:
            return
        visiting.add(cid)
        for dep in sorted(const_deps.get(cid, set())):
            dfs(dep)
        visiting.remove(cid)
        visited.add(cid)
        order.append(cid)

    for cid in sorted(out.consts):
        dfs(cid)
    return order
