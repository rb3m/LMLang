"""Shared source-level self tail-call sites (ADR-051 item 1).

Only walk tail positions of the function body. In particular, do not descend into
try, lambdas, argument expressions, contracts or examples. Node identities let
the interpreter and lowering use exactly the same decision without changing ASTs.
"""
from .resolve import head


def tail_sites(body, name):
    sites = set()

    def walk(e):
        h = head(e)
        if h == name:
            sites.add(id(e))
        elif h == "if":
            walk(e.items[2])
            walk(e.items[3])
        elif h in ("let", "let?"):
            walk(e.items[2])
        elif h == "do" and len(e.items) > 1:
            walk(e.items[-1])
        elif h == "match":
            for arm in e.items[2:]:
                walk(arm.items[1])

    walk(body)
    return sites


class TailArgs:
    """Internal interpreter result: start another iteration with these arguments."""
    def __init__(self, args):
        self.args = args
