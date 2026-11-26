"""Literal pattern validation and opaque-pattern external value checks."""
from __future__ import annotations

from .diag import make
from .pat_compile import PatternError, compile_pattern
from .sexpr import Atom


def discharged_compile(ck, info, args, node, path):
    """Validate literal compile sites and retain their runtime fault guard."""
    if info.qual != "pat.compile" or len(args) != 1:
        return False
    literal = args[0]
    if not isinstance(literal, Atom) or literal.kind != "str":
        return False
    try:
        compile_pattern(literal.value)
    except PatternError as error:
        m = ck.cur_mod
        if m.report:
            ck.prog.diags.append(make(
                "E-PATTERN", m.file, literal.line, literal.col,
                f"invalid pattern at offset {error.pos}: {error.reason}",
                path=path, expected="a valid pattern", found=error.reason,
                data={"pos": error.pos, "reason": error.reason}))
        return True
    fq = ck.cur_fn.qual if ck.cur_fn else ""
    ck.prog.discharged[id(node)] = (
        ck.cur_mod.file, node.line, node.col, path, fq)
    return True


def check_external_type(ck, m, t, node, path):
    """Primitive handles cannot appear in external constants, even nested."""
    opaque = ck.primitive_opaque(t)
    if opaque:
        ck.diag(m, "E-TYPE", node, path,
                f"external constants cannot contain {opaque} values",
                expected=f"a type without {opaque}", found=ck.s.show(t))
