"""Module constants checking, cycle detection, and check-time evaluation (ADR-058)."""
from __future__ import annotations

import io

from .diag import make
from .interp import Interp
from .program import ConstInfo, FnInfo, ModInfo, Program
from .runner import runtime_diag
from .sexpr import Atom, SList
from .types import children
from .values import Denied, LmFail, Overflow, Violation

STEP_BUDGET = 1_000_000


def has_type_vars(t) -> bool:
    if not isinstance(t, tuple) or not t:
        return False
    if t[0] in ("V", "M"):
        return True
    return any(has_type_vars(c) for c in children(t))


def check_const(ck, m: ModInfo, c: ConstInfo):
    """Check a constant declaration: value type matches declared type, no effects, no fails, no type variables."""
    if "value" not in c.clauses or len(c.clauses["value"][0].items) != 2:
        return
    val_node = c.clauses["value"][0].items[1]
    path = f"{m.name}/{c.name}/value/1"
    ck.cur_mod, ck.cur_fn = m, None
    ck.constraints, ck.eq_checks = [], []

    def run():
        ck.clear_facts()
        return ck.infer(m, val_node, {}, path)

    vt = ck.sandbox(m, f"constant `{c.name}`", run)
    if c.declared_type is not None:
        ck.expect(m, c.declared_type, vt, val_node, path, "constant value")
    ck.note_keys(vt, val_node, path)
    ck.check_eq(m)
    wvt = ck.s.resolve(vt)
    if has_type_vars(wvt):
        ck.diag(m, "E-TYPE", val_node, path,
                f"constant `{c.name}` has generic type {ck.s.show(wvt)}; type variables are not allowed in constants",
                found=ck.s.show(wvt))


class ConstBudgetExhausted(Exception):
    """Raised when check-time evaluation of a constant exceeds the step budget."""


class ConstEvalError(Exception):
    """Raised internally when evaluation of a constant failed and was diagnosed."""


class ConstEvaluator(Interp):
    """Interpreter with a step budget for check-time evaluation of module constants."""

    def __init__(self, prog: Program, ck=None, budget: int = STEP_BUDGET):
        super().__init__(prog, allowed=(), contracts=True, out=io.StringIO(), stdin=io.BytesIO(), err=io.StringIO())
        self.budget = budget
        self.steps = 0
        self.ck = ck
        self.failed_consts: set[str] = set()

    def ev(self, e, env, m: ModInfo):
        self.steps += 1
        if self.steps > self.budget:
            raise ConstBudgetExhausted()
        return super().ev(e, env, m)

    def call_fn(self, f: FnInfo, args):
        self.steps += 1
        if self.steps > self.budget:
            raise ConstBudgetExhausted()
        return super().call_fn(f, args)

    def eval_const(self, c: ConstInfo):
        if c.value is not None:
            return c.value
        if c.qual in self.failed_consts:
            raise ConstEvalError()
        if c.qual in self.evaluating_consts:
            if self.ck is not None:
                self.ck.diag(c.mod, "E-CYCLE", c.node, f"{c.mod.name}/{c.name}",
                             f"constant cycle involving `{c.name}`")
            self.failed_consts.add(c.qual)
            raise ConstEvalError()
        if "value" not in c.clauses or len(c.clauses["value"][0].items) != 2:
            return None
        val_expr = c.clauses["value"][0].items[1]
        self.evaluating_consts.add(c.qual)
        saved_steps = self.steps
        self.steps = 0
        try:
            val = self.ev(val_expr, {}, c.mod)
            c.value = val
            return val
        except ConstEvalError:
            self.failed_consts.add(c.qual)
            raise
        except ConstBudgetExhausted:
            if self.ck is not None:
                self.ck.diag(c.mod, "E-CONST-BUDGET", c.node, f"{c.mod.name}/{c.name}",
                             f"evaluation of constant `{c.name}` exceeded step budget of {self.budget:,}")
            self.failed_consts.add(c.qual)
            raise ConstEvalError()
        except Overflow as ex:
            if self.ck is not None:
                self.ck.diag(c.mod, ex.code, c.node, f"{c.mod.name}/{c.name}",
                             f"{ex.code}: constant `{c.name}` evaluation overflowed")
            self.failed_consts.add(c.qual)
            raise ConstEvalError()
        except Violation as ex:
            if self.ck is not None:
                self.ck.diag(c.mod, ex.code, c.node, f"{c.mod.name}/{c.name}",
                             f"{ex.code}: contract violation during constant `{c.name}` evaluation")
            self.failed_consts.add(c.qual)
            raise ConstEvalError()
        except LmFail as ex:
            if self.ck is not None:
                self.ck.diag(c.mod, "E-FAILS-UNDECLARED", c.node, f"{c.mod.name}/{c.name}",
                             f"constant `{c.name}` evaluation failed with `{ex.id}`")
            self.failed_consts.add(c.qual)
            raise ConstEvalError()
        except Denied as ex:
            if self.ck is not None:
                self.ck.diag(c.mod, "E-EFFECT-UNDECLARED", c.node, f"{c.mod.name}/{c.name}",
                             f"constant `{c.name}` evaluation attempted effect `{ex.eff}`")
            self.failed_consts.add(c.qual)
            raise ConstEvalError()
        except Exception as ex:
            d = runtime_diag(ex, it=self)
            if d is not None:
                if self.ck is not None:
                    self.ck.diag(c.mod, d.code, c.node, f"{c.mod.name}/{c.name}", d.msg)
                self.failed_consts.add(c.qual)
                raise ConstEvalError()
            else:
                raise
        finally:
            self.steps = saved_steps
            self.evaluating_consts.discard(c.qual)


def find_const(ck, m: ModInfo, name: str, node, path):
    """Resolve a constant name (bare in own module or qualified from another)."""
    if "." in name:
        q, base = name.split(".", 1)
        m2 = ck.find_module(m, q, node, path)
        if m2 is None:
            return None
        c = m2.consts.get(base)
        if c is None:
            cands = [f"{q}.{n}" for n in sorted(m2.exported_consts)]
            ck.diag(m, "E-NAME-UNRESOLVED", node, path, f"module `{q}` has no constant `{base}`",
                    expected=" ".join(cands[:8]), found=name)
            return None
        if base not in m2.exported_consts:
            ck.diag(m, "E-NOT-EXPORTED", node, path, f"`{name}` exists but module `{q}` does not export it", found=name)
            return None
        return c
    return m.consts.get(name)


def check_const_cycles(prog: Program, ck):
    """Detect cycles in the static reference graph that involve constants (ADR-058 item 2)."""
    # Graph: sym qual -> set of target quals
    graph: dict[str, set[str]] = {}
    for (mn, path), target in prog.refs.items():
        segs = path.split("/")
        if len(segs) > 1 and "." in target and not target.startswith("prelude."):
            if any(s.startswith("example") for s in segs):
                continue
            owner = f"{segs[0]}.{segs[1]}"
            graph.setdefault(owner, set()).add(target)

    # For each const, do DFS to detect cycles
    all_consts = {c.qual: c for m in prog.modules.values() for c in m.consts.values()}

    def find_cycle(start: str, curr: str, visited: list[str]) -> list[str] | None:
        for nxt in sorted(graph.get(curr, set())):
            if nxt == start:
                return visited + [nxt]
            if nxt in visited:
                continue
            res = find_cycle(start, nxt, visited + [nxt])
            if res is not None:
                return res
        return None

    reported = set()
    for cqual, c in sorted(all_consts.items()):
        cyc = find_cycle(cqual, cqual, [cqual])
        if cyc is not None:
            cname = c.qual
            if cname not in reported:
                reported.add(cname)
                cyc_str = " -> ".join(cyc)
                ck.diag(c.mod, "E-CYCLE", c.node, f"{c.mod.name}/{c.name}", f"constant cycle: {cyc_str}")


def eval_all_consts(prog: Program, ck, budget: int = STEP_BUDGET):
    """Check-time evaluation of all constants in dependency order with step budget (ADR-058 item 3)."""
    if any(d.severity == "error" for d in prog.diags):
        return
    evaluator = ConstEvaluator(prog, ck=ck, budget=budget)
    for mn in sorted(prog.modules):
        m = prog.modules[mn]
        for cname in sorted(m.consts):
            try:
                evaluator.get_const(m.consts[cname])
            except ConstEvalError:
                pass
