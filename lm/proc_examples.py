"""Checked, constant subprocess scripts for hermetic effect examples."""
from __future__ import annotations

from dataclasses import dataclass

from .resolve import head
from .sexpr import Atom, SList
from .types import INT, STR
from .values import Pair, Rec, Var, in_range


CATEGORIES = frozenset(("invalid-request", "not-found", "permission", "spawn",
                        "io", "timeout", "limit", "invalid-utf8"))


@dataclass(frozen=True)
class ProcEntry:
    argv: tuple
    stdin: str
    cwd: Var
    env: tuple
    outcome: object


class ProcMismatch(Exception):
    """An uncatchable example mismatch, distinct from a program's LM error."""


def structure(clause):
    """Return typed leaf expressions, or a structural error message."""
    items = clause.items[1:]
    if len(items) < 2 or clause_name(items[0]) != "argv":
        return None, "proc needs argv first and an outcome last"
    outcome = items[-1]
    kind = clause_name(outcome)
    if kind not in ("exited", "signaled", "error"):
        return None, "proc needs an exited, signaled or error outcome last"
    leaves, seen = [], set()
    for i, sub in enumerate(items[:-1], 1):
        name = clause_name(sub)
        if name not in ("argv", "stdin", "cwd", "env"):
            return None, "unknown proc request clause"
        if name != "env" and name in seen:
            return None, f"duplicate proc {name} clause"
        seen.add(name)
        arity = {"argv": None, "stdin": 1, "cwd": 1, "env": 2}[name]
        if arity is not None and len(sub.items) != arity + 1:
            return None, f"proc {name} takes {arity} value(s)"
        leaves.extend((f"/{i}/{j}", v, STR)
                      for j, v in enumerate(sub.items[1:], 1))
    oi = len(items)
    if len(outcome.items) < 2:
        return None, f"proc {kind} needs one value"
    leaves.append((f"/{oi}/1", outcome.items[1],
                   STR if kind == "error" else INT))
    if kind != "exited" and len(outcome.items) != 2:
        return None, f"proc {kind} takes one value"
    seen = set()
    for i, sub in enumerate(outcome.items[2:], 2):
        name = clause_name(sub)
        if name not in ("stdout", "stderr"):
            return None, "unknown proc exited clause"
        if name in seen:
            return None, f"duplicate proc {name} clause"
        seen.add(name)
        if len(sub.items) != 2:
            return None, f"proc {name} takes one value"
        leaves.append((f"/{oi}/{i}/1", sub.items[1], STR))
    return leaves, None


def clause_name(node):
    if (isinstance(node, SList) and node.items
            and isinstance(node.items[0], Atom)
            and node.items[0].kind == "sym"):
        return node.items[0].value
    return None


def check_proc(metadata, clause, path):
    """Check syntax and leaf types using the enclosing checker's sandbox."""
    leaves, error = structure(clause)
    if error:
        metadata.error(clause, path, error)
        return False
    ck, m = metadata.ck, metadata.m
    start = len(ck.prog.diags)

    def run():
        for suffix, value, want in leaves:
            vp = path + suffix
            ck.expect(m, want, ck.infer(m, value, {}, vp), value, vp,
                      "proc example clause")

    ck.sandbox(m, "a proc example clause", run)
    ck.check_eq(m)
    diags = ck.prog.diags[start:]
    del ck.prog.diags[start:]
    for diag in diags:
        metadata.error(clause, diag.path, diag.msg)
    return not diags


def proc_values(prog, m, clause):
    """Evaluate only leaves, preserving ordered requests and env pairs."""
    from .consts import ConstEvalError, ConstEvaluator

    evaluator = ConstEvaluator(prog)

    def values(sub):
        return tuple(evaluator.ev(value, {}, m) for value in sub.items[1:])

    request = {"stdin": ("",), "cwd": ()}
    env = []
    for sub in clause.items[1:-1]:
        vals = values(sub)
        if head(sub) == "env":
            env.append(Pair(*vals))
        else:
            request[head(sub)] = vals
    out = clause.items[-1]
    kind = head(out)
    number = evaluator.ev(out.items[1], {}, m)
    if kind == "error":
        if number not in CATEGORIES:
            raise ConstEvalError("invalid proc error category")
        outcome = number
    else:
        if type(number) is not int or not in_range(number):
            raise ConstEvalError("proc exit or signal must fit signed Int64")
        streams = {head(sub): values(sub)[0] for sub in out.items[2:]}
        variant = Var("proc", "Exited" if kind == "exited" else "Signaled",
                      (number,))
        outcome = Rec("proc.Result", (("exit", variant),
                      ("stdout", streams.get("stdout", "")),
                      ("stderr", streams.get("stderr", ""))))
    cwd = (Var("", "Some", request["cwd"]) if request["cwd"]
           else Var("", "None"))
    return (ProcEntry(request["argv"], request["stdin"][0], cwd,
                      tuple(env), outcome),)
