"""Tree-walking evaluator over checked programs (docs/SPEC.md section 11)."""
from __future__ import annotations

import math
import sys

from .prelude import SPECIAL, form_method
from .prims import PRIMS
from .rand_prims import SplitMix64
from .program import ModInfo, Program
from .resolve import head
from .sexpr import Atom, SList
from .tree import build
from .tailcall import TailArgs, tail_sites
from .values import UNIT, Closure, Denied, FloatFault, LmFail, Named, Overflow, Pair, ProofViolation, PyFn, Rec, Var, Violation, in_range


def _checked(op, r, a, b):
    """Every Int result is checked; leaving the 64-bit range is the fault E-OVERFLOW (ADR-029/030)."""
    if in_range(r):
        return r
    raise Overflow(op, (a, b))


def finite(op, r, operands):
    """Every Float result is checked: NaN or an infinity is the fault E-FLOAT; -0.0 becomes 0.0 (ADR-039)."""
    if math.isfinite(r):
        return r + 0.0
    raise FloatFault(op, operands)


def _arith(op, int_op, float_op):
    def f(a, b):
        if isinstance(a, float):
            return finite(op, float_op(a, b), (a, b))
        return _checked(op, int_op(a, b), a, b)
    return f


def _fdiv(a, b):
    return a / b if b != 0.0 else math.nan  # Python raises on 0.0; IEEE gives inf/nan, both faults


def _div(a, b):
    if isinstance(a, float):
        return finite("/", _fdiv(a, b), (a, b))
    if b == 0:
        raise LmFail("DivZero")
    return _checked("/", a // b, a, b)


def _mod(a, b):
    if b == 0:
        raise LmFail("DivZero")
    return a % b


PRELUDE_FNS = {
    "+": _arith("+", int.__add__, float.__add__), "-": _arith("-", int.__sub__, float.__sub__),
    "*": _arith("*", int.__mul__, float.__mul__), "/": _div, "mod": _mod,
    "=": lambda a, b: a == b, "!=": lambda a, b: a != b,
    "<": lambda a, b: a < b, "<=": lambda a, b: a <= b, ">": lambda a, b: a > b, ">=": lambda a, b: a >= b,
    "not": lambda a: not a, "len": len, "cons": lambda x, xs: (x,) + xs, "pair": Pair,
}


def sanitize_arg(a: str) -> str:
    try:
        return a.encode("utf-8", errors="surrogateescape").decode("utf-8", errors="replace")
    except Exception:
        return a


class Interp:
    """Frames are [kind, obj, site, args] with kind fn|lam|cb|top. They are popped on normal return only,
    so after a fault `frames` still describes where it happened (lm/fault.py reads it)."""

    def __init__(self, prog: Program, allowed=(), contracts=True, out=None, stdin=None, err=None, args=(), seed=None):
        self.prog, self.allowed, self.contracts = prog, set(allowed), contracts
        self.out = out if out is not None else sys.stdout
        self.stdin = stdin if stdin is not None else sys.stdin
        self.err = err if err is not None else sys.stderr
        self.args = tuple(sanitize_arg(a) for a in args)
        self.rng = SplitMix64(seed)
        self.frames: list = []
        self.tail_sites = {}  # fn id -> source node identities; cached for this checked program
        self.evaluating_consts = set()
        self.reset()

    def reset(self):
        self.frames[:] = [["top", None, None, None]]
        self.evaluating_consts.clear()

    # ---- calls ---------------------------------------------------------------------------
    def apply(self, fv, args):
        if isinstance(fv, Closure):
            self.frames.append(["lam", fv, None, args])
            r = self.ev(fv.body, {**fv.env, **dict(zip(fv.params, args))}, fv.mod)
        elif isinstance(fv, Named):
            return self.call_fn(fv.info, args)
        else:  # a prelude fn invoked as a callback by a prim (direct calls go through ev)
            self.frames.append(["cb", fv, None, args])
            r = fv.f(*args)
        self.frames.pop()
        return r

    def call_fn(self, f, args):
        for e in sorted(f.eff):
            if e not in self.allowed:
                raise Denied(e, f)
        self.frames.append(["fn", f, None, args])
        body = f.clauses["body"][0].items[1]
        if f.qual not in self.tail_sites:
            self.tail_sites[f.qual] = tail_sites(body, f.name)
        saved = [] if self.contracts and f.clauses.get("ensures") else None
        while True:
            # A new environment each time also keeps captured parameters immutable.
            env = dict(zip((p for p, _ in f.params), args))
            self.frames[-1] = ["fn", f, None, args]
            if self.contracts:
                for k, c in enumerate(f.clauses.get("requires", [])):
                    if self.ev(c.items[1], env, f.mod) is not True:
                        raise Violation("E-REQUIRES-VIOLATED", c, f, f"requires#{k}", args)
            if saved is not None:
                saved.append(args)
            r = PRIMS[body.items[1].value](self, *args) if head(body) == "prim" else self.ev(body, env, f.mod)
            if not isinstance(r, TailArgs):
                break
            args = r.args
        for args in reversed(saved or []):
            self.frames[-1] = ["fn", f, None, args]
            env2 = {**dict(zip((p for p, _ in f.params), args)), "result": r}
            for k, c in enumerate(f.clauses.get("ensures", [])):
                if self.ev(c.items[1], env2, f.mod) is not True:
                    raise Violation("E-ENSURES-VIOLATED", c, f, f"ensures#{k}", args)
        self.frames.pop()
        return r

    # ---- expressions -----------------------------------------------------------------------
    def ev(self, e, env, m: ModInfo):
        if isinstance(e, Atom):
            return self.atom(e, env, m)
        frame = self.frames[-1]
        if frame[0] == "fn" and id(e) in self.tail_sites[frame[1].qual]:
            # Evaluate all arguments before the loop replaces any parameter.
            return TailArgs([self.ev(a, env, m) for a in e.items[1:]])
        h = e.items[0]
        if isinstance(h, Atom):
            if h.kind == "sym" and h.value in SPECIAL:
                return getattr(self, form_method("s_", h.value))(e, env, m)
            if h.kind == "type":
                return Var(*self.vkey(h.value, m), tuple(self.ev(a, env, m) for a in e.items[1:]))
        fv = self.ev(h, env, m)
        args = [self.ev(a, env, m) for a in e.items[1:]]
        self.frames[-1][2] = e
        if id(e) in self.prog.discharged:
            try:
                if isinstance(fv, PyFn):
                    return fv.f(*args)
                return self.apply(fv, args)
            except LmFail as f:
                if f.id in ("DivZero", "OutOfRange"):
                    raise ProofViolation(self.prog.discharged[id(e)])
                raise
        if isinstance(fv, PyFn):
            return fv.f(*args)
        return self.apply(fv, args)

    def atom(self, e, env, m):
        k, v = e.kind, e.value
        if k in ("int", "float", "str"):
            return v
        if k == "type":
            return Var(*self.vkey(v, m), ())
        if v == "true":
            return True
        if v == "false":
            return False
        if v == "unit":
            return UNIT
        if v in env:
            return env[v]
        if v in PRELUDE_FNS:
            return PyFn(v, PRELUDE_FNS[v])
        if "." in v:
            q, b = v.split(".", 1)
            m2 = self.prog.modules[q]
            if b in m2.consts:
                return self.get_const(m2.consts[b])
            return Named(m2.fns[b])
        if v in m.consts:
            return self.get_const(m.consts[v])
        return Named(m.fns[v])

    def get_const(self, c):
        if c.value is not None:
            return c.value
        return self.eval_const(c)

    def eval_const(self, c):
        if c.value is not None:
            return c.value
        if c.qual in self.evaluating_consts:
            raise LmFail("ConstCycle")
        if "value" not in c.clauses or len(c.clauses["value"][0].items) != 2:
            return None
        val_expr = c.clauses["value"][0].items[1]
        self.evaluating_consts.add(c.qual)
        try:
            val = self.ev(val_expr, {}, c.mod)
            c.value = val
            return val
        finally:
            self.evaluating_consts.discard(c.qual)

    def vkey(self, name, m):
        if "." in name:
            q, b = name.split(".", 1)
            return q, b
        return (m.name, name) if name in m.variants else ("", name)

    def err_id(self, name, m):
        if "." in name:
            return name
        return f"{m.name}.{name}" if name in m.errors else name

    def s_if(self, e, env, m):
        return self.ev(e.items[2] if self.ev(e.items[1], env, m) else e.items[3], env, m)

    def s_let(self, e, env, m):
        env = dict(env)
        for b in e.items[1].items:
            env[b.items[0].value] = self.ev(b.items[1], env, m)
        return self.ev(e.items[2], env, m)

    def s_let_q(self, e, env, m):
        env = dict(env)
        for b in e.items[1].items:
            o = self.ev(b.items[1], env, m)
            if o.name == "None":
                return o
            env[b.items[0].value] = o.args[0]
        return self.ev(e.items[2], env, m)

    def s_do(self, e, env, m):
        r = UNIT
        for a in e.items[1:]:
            r = self.ev(a, env, m)
        return r

    def s_for(self, e, env, m):
        name = e.items[1].items[0].value
        xs = self.ev(e.items[1].items[1], env, m)
        body = e.items[2]
        for val in xs:
            body_env = dict(env)
            body_env[name] = val
            self.ev(body, body_env, m)
        return UNIT

    def s_match(self, e, env, m):
        v = self.ev(e.items[1], env, m)
        for arm in e.items[2:]:
            binds: dict = {}
            if self.pmatch(arm.items[0], v, binds, m):
                return self.ev(arm.items[1], {**env, **binds}, m)
        raise RuntimeError("non-exhaustive match reached at runtime (checker bug)")

    def pmatch(self, p, v, binds, m):
        if isinstance(p, Atom):
            if p.kind in ("int", "str"):
                return type(v) is type(p.value) and v == p.value
            if p.kind == "type":
                return isinstance(v, Var) and (v.mod, v.name) == self.vkey(p.value, m) and not v.args
            x = p.value
            if x in ("_", "unit"):
                return True
            if x in ("true", "false"):
                return v is (x == "true")
            binds[x] = v
            return True
        h = p.items[0].value
        subs = p.items[1:]
        if h == "list":
            return isinstance(v, tuple) and len(v) == len(subs) and all(
                self.pmatch(sp, a, binds, m) for sp, a in zip(subs, v))
        if h == "cons":
            return isinstance(v, tuple) and len(v) >= 1 and self.pmatch(subs[0], v[0], binds, m) and self.pmatch(subs[1], v[1:], binds, m)
        if h == "pair":
            return isinstance(v, Pair) and len(subs) == 2 and self.pmatch(subs[0], v.a, binds, m) and self.pmatch(subs[1], v.b, binds, m)
        key = self.vkey(h, m)
        return isinstance(v, Var) and (v.mod, v.name) == key and len(v.args) == len(subs) and all(
            self.pmatch(sp, a, binds, m) for sp, a in zip(subs, v.args))

    def s_lam(self, e, env, m):
        return Closure(tuple(p.value if isinstance(p, Atom) else p.items[0].value for p in e.items[1].items), e.items[2], env, m)

    def s_list(self, e, env, m):
        return tuple(self.ev(a, env, m) for a in e.items[1:])

    def _qual_type(self, name, m):
        return name if "." in name else f"{m.name}.{name}"

    def s_new(self, e, env, m):
        q = self._qual_type(e.items[1].value, m)
        vals = {p.items[0].value: self.ev(p.items[1], env, m) for p in e.items[2:]}
        return Rec(q, tuple((f, vals[f]) for f, _ in self.prog.type_index[q].fields))

    def s_get(self, e, env, m):
        return dict(self.ev(e.items[1], env, m).items)[e.items[2].value]

    def s_with(self, e, env, m):
        r = self.ev(e.items[1], env, m)
        upd = {p.items[0].value: self.ev(p.items[1], env, m) for p in e.items[2:]}
        return Rec(r.t, tuple((f, upd.get(f, x)) for f, x in r.items))

    def s_and(self, e, env, m):
        return all(self.ev(a, env, m) is True for a in e.items[1:])

    def s_or(self, e, env, m):
        return any(self.ev(a, env, m) is True for a in e.items[1:])

    def s_note(self, e, env, m):
        return UNIT

    def s_fail(self, e, env, m):
        raise self.fail_value(e, env, m)

    def fail_value(self, e, env, m):
        return LmFail(self.err_id(e.items[1].value, m), tuple(self.ev(a, env, m) for a in e.items[2:]))

    def s_try(self, e, env, m):
        depth = len(self.frames)
        try:
            return self.ev(e.items[1], env, m)
        except LmFail as f:
            del self.frames[depth:]
            for c in e.items[2:]:
                if self.err_id(c.items[1].value, m) == f.id:
                    binds = dict(zip((a.value for a in c.items[2].items), f.args_))
                    return self.ev(c.items[3], {**env, **binds}, m)
            raise

    def s_mapof(self, e, env, m):
        """Keys are constants; values are evaluated left to right in source order (ADR-049 item 4)."""
        return build([(self.atom(p.items[0], env, m), self.ev(p.items[1], env, m)) for p in e.items[1:]], False)

    def s_setof(self, e, env, m):
        return build([(self.atom(x, env, m), UNIT) for x in e.items[1:]], True)

    def s_prim(self, e, env, m):
        raise RuntimeError("(prim ...) is only valid as a whole fn body")

    def s_catch(self, e, env, m):
        raise RuntimeError("(catch ...) outside try")
