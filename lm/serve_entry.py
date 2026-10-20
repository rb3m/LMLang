"""Check named HTTP entry points independently of the selected adapter."""
from __future__ import annotations

from .diag import make
from .types import nom


def serve_problem(f):
    """A server entry is exactly Request -> Response and declares no failures."""
    if len(f.params) != 1 or f.params[0][1] != nom("http.Request"):
        return f"{f.qual} must take exactly one http.Request parameter"
    if f.ret != nom("http.Response"):
        return f"{f.qual} must return http.Response"
    if f.fails:
        return f"{f.qual} declares fails; a server handler must handle every failure"
    return None


def check_serve(prog, name):
    """Append E-SERVE on invalid selection and return the selected FnInfo."""
    mname, fname = name.split(".", 1)
    mod = prog.modules.get(mname)
    f = mod.fns.get(fname) if mod else None
    problem = serve_problem(f) if f else f"unknown server handler `{name}`"
    if problem is None:
        return f
    node = f.node if f else None
    prog.diags.append(make(
        "E-SERVE", mod.file if mod else "", node.line if node else 1,
        node.col if node else 1, problem, f"{mname}/{fname}"))
    return None
