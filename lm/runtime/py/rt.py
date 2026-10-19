"""Runtime support for Python programs emitted by `lm build --target py` (ADR-062)."""
from __future__ import annotations
import errno, json, math, os, re, struct, sys, threading, time

class Site:
    __slots__ = ("file", "line", "col", "path", "fn")
    def __init__(self, file: str, line: int, col: int, path: str, fn: str):
        self.file, self.line, self.col, self.path, self.fn = file, line, col, path, fn

sites: list[Site] = []
stdlib_mods: set[str] = set()
max_depth, depth = 500000, 0

def enter():
    global depth
    depth += 1
    if depth > max_depth:
        depth = 0
        fault("E-RECURSION-LIMIT", -1, f"recursion limit reached ({max_depth} nested calls)", "")

class LmFail(Exception):
    def __init__(self, id: str, args: tuple = ()):
        super().__init__(id)
        self.id, self.args_ = id, tuple(args)
    def __str__(self):
        return f"(fail {self.id}" + "".join(" " + show(a) for a in self.args_) + ")"

class Fault(Exception):
    def __init__(self, diag: dict):
        super().__init__(diag["code"])
        self.diag = diag

def lm_fail(id: str, *args): raise LmFail(id, args)

def fault(code: str, site: int, msg: str, found: str):
    d = {"code": code, "severity": "error", "line": 1, "col": 1, "file": "", "path": "", "msg": msg, "expected": "", "found": found, "fix": []}
    if site >= 0:
        s = sites[site]
        d["file"], d["line"], d["col"], d["path"] = s.file, s.line, s.col, s.path
    raise Fault(d)

def violation(code: str, site: int, *args):
    s = sites[site]
    clause = "ensures" if code == "E-ENSURES-VIOLATED" else "requires"
    fault(code, site, f"{clause} of {s.fn} is false for arguments {show_args(args)}", show_args(args))

class Unit:
    def __repr__(self): return "unit"
UNIT = Unit()

class Var:
    __slots__ = ("mod", "name", "args")
    def __init__(self, mod: str, name: str, args: tuple = ()):
        self.mod, self.name, self.args = mod, name, tuple(args)

V_NONE = Var("", "None", ())
def mk_some(v): return Var("", "Some", (v,))
def has_tag(v, tag: str) -> bool:
    return isinstance(v, Var) and (f"{v.mod}.{v.name}" if v.mod else v.name) == tag

class Pair:
    __slots__ = ("a", "b")
    def __init__(self, a, b): self.a, self.b = a, b

class Rec:
    __slots__ = ("t", "items")
    def __init__(self, t: str, items): self.t, self.items = t, tuple(items)

def get_field(r, name: str):
    for k, v in r.items:
        if k == name: return v
    raise KeyError(name)

def with_fields(r, *pairs):
    up = dict(pairs)
    return Rec(r.t, tuple((k, up.get(k, v)) for k, v in r.items))

class Closure:
    __slots__ = ("fn", "caps")
    def __init__(self, fn, caps: tuple): self.fn, self.caps = fn, caps
    def __call__(self, *args): return self.fn(*self.caps, *args)

def equal(a, b) -> bool:
    if type(a) is not type(b): return False
    if isinstance(a, (int, str, float)): return a == b
    if isinstance(a, bool) or a is UNIT or b is UNIT: return a is b
    if isinstance(a, tuple): return len(a) == len(b) and all(equal(x, y) for x, y in zip(a, b))
    if isinstance(a, Var): return a.name == b.name and a.mod == b.mod and equal(a.args, b.args)
    if isinstance(a, Rec): return a.t == b.t and equal(a.items, b.items)
    if isinstance(a, Pair): return equal(a.a, b.a) and equal(a.b, b.b)
    if isinstance(a, Closure): return a is b
    if "Coll" in globals() and isinstance(a, Coll):
        if a.is_set != b.is_set or size(a.root) != size(b.root): return False
        return all(equal(k1, k2) and equal(v1, v2) for (k1, v1), (k2, v2) in zip(items(a.root), items(b.root)))
    return a == b

def less(a, b) -> bool: return a < b if type(a) is type(b) else False
def float_text(x: float) -> str: return repr(x + 0.0)
_ESC = {'"': '\\"', "\\": "\\\\", "\n": "\\n", "\t": "\\t"}

def _esc_str(s: str) -> str:
    out = []
    for c in s:
        e = _ESC.get(c)
        if e is not None: out.append(e)
        else:
            cp = ord(c)
            if cp < 0x20 or (0x7F <= cp <= 0x9F): out.append(f"\\u{{{cp:x}}}")
            else: out.append(c)
    return '"' + "".join(out) + '"'

def show(v) -> str:
    if v is True: return "true"
    if v is False: return "false"
    if isinstance(v, int): return str(v)
    if isinstance(v, float): return float_text(v)
    if isinstance(v, str): return _esc_str(v)
    if isinstance(v, tuple): return "(list" + "".join(" " + show(x) for x in v) + ")"
    if v is UNIT: return "unit"
    if isinstance(v, Var):
        n = f"{v.mod}.{v.name}" if v.mod else v.name
        return f"({n}" + "".join(" " + show(a) for a in v.args) + ")" if v.args else n
    if isinstance(v, Rec):
        return f"(new {v.t}" + "".join(f" ({k} {show(x)})" for k, x in v.items) + ")"
    if isinstance(v, Pair): return f"(pair {show(v.a)} {show(v.b)})"
    if "Coll" in globals() and isinstance(v, Coll): return show_coll(v)
    return "<fn>"

def show_args(args) -> str: return "(" + " ".join(show(a) for a in args) + ")"
def demangle(s: str) -> str:
    mod, _, name = s.partition("_X_")
    return mod.replace("_", "-") + "." + name.replace("_", "-")

def lm_frames() -> tuple[list[str], str]:
    f, names, user = sys._getframe(2), [], ""
    while f:
        fn = f.f_code.co_name
        if fn.startswith("F_"):
            q = demangle(fn[2:])
            names.append(q)
            mod = q.split(".")[0]
            if not user and mod not in stdlib_mods: user = q
        elif fn.startswith("L") and "_" in fn:
            names.append(f"(lam) in {demangle(fn.split('_', 1)[1])}")
        f = f.f_back
    return names, user

def pick_frames(names: list[str], user: str) -> list[str]:
    if len(names) <= 3: return names
    for k, n in enumerate(names):
        if n == user: return names if k < 3 else names[:2] + [n]
    return names[:3]

def num_fault(code: str, op: str, operands: list, site: int, callback: bool):
    names, user = lm_frames()
    if callback: names.insert(0, f"`{op}` (callback)")
    shown = pick_frames(names, user)
    where = " <- ".join(shown) if shown else "top level"
    expr = f"({op}" + "".join(" " + show(a) for a in operands) + ")"
    replay = "unavailable (compiled binary)"
    if code == "E-FLOAT":
        lead, bounds = "Float result not finite", [-1.7976931348623157e+308, 1.7976931348623157e+308]
        guide = "Fix the arithmetic, validate input, or add a justified precondition; a non-finite Float cannot be caught."
    else:
        lead, bounds = "Int overflow", [INT_MIN, INT_MAX]
        guide = "Fix the arithmetic, validate input, or add a justified precondition; overflow cannot be caught."
    d = {"code": code, "severity": "error", "line": 1, "col": 1, "file": "", "path": "", "found": expr, "fix": []}
    if site >= 0:
        s = sites[site]
        d["file"], d["line"], d["col"], d["path"] = s.file, s.line, s.col, s.path
    elif user: d["path"] = user.replace(".", "/") + "/body"
    d["msg"] = f"{lead}: {expr} is outside [{show(bounds[0])}, {show(bounds[1])}] in {where}; replay: {replay}. {guide}"
    d["data"] = {"op": op, "operands": list(operands), "bounds": bounds, "frames": shown, "frames_omitted": len(names) - len(shown), "user_path": d["path"], "replay": replay}
    raise Fault(d)

def overflow(op: str, a: int, b: int, site: int): num_fault("E-OVERFLOW", op, [a, b], site, site < 0)

INT_MIN, INT_MAX = -(2 ** 63), 2 ** 63 - 1
def fbits(u: int) -> float: return struct.unpack('<d', struct.pack('<Q', u))[0]

def farith(op: str, a: float, b: float, site: int) -> float:
    try:
        if op == "+": c = a + b
        elif op == "-": c = a - b
        elif op == "*": c = a * b
        else:
            if b == 0.0: num_fault("E-FLOAT", op, [a, b], site, site < 0)
            c = a / b
    except OverflowError: num_fault("E-FLOAT", op, [a, b], site, site < 0)
    if not math.isfinite(c): num_fault("E-FLOAT", op, [a, b], site, site < 0)
    return c + 0.0

def add(x, y, site: int):
    if isinstance(x, float): return farith("+", x, y, site)
    c = x + y
    if not INT_MIN <= c <= INT_MAX: overflow("+", x, y, site)
    return c

def sub(x, y, site: int):
    if isinstance(x, float): return farith("-", x, y, site)
    c = x - y
    if not INT_MIN <= c <= INT_MAX: overflow("-", x, y, site)
    return c

def mul(x, y, site: int):
    if isinstance(x, float): return farith("*", x, y, site)
    c = x * y
    if not INT_MIN <= c <= INT_MAX: overflow("*", x, y, site)
    return c

def div(x, y, site: int):
    if isinstance(x, float): return farith("/", x, y, site)
    if y == 0: lm_fail("DivZero")
    if x == INT_MIN and y == -1: overflow("/", x, y, site)
    return x // y

def mod(x, y, site: int):
    if y == 0: lm_fail("DivZero")
    return x % y

def safe_div(x, y, site: int):
    if isinstance(x, float): return farith("/", x, y, site)
    if y == 0: fault("E-PROOF-VIOLATED", site, f"discharged operation at {sites[site].path} violated", "")
    if x == INT_MIN and y == -1: overflow("/", x, y, site)
    return x // y

def safe_mod(x, y, site: int):
    if y == 0: fault("E-PROOF-VIOLATED", site, f"discharged operation at {sites[site].path} violated", "")
    return x % y

def safe_list_nth(xs, i: int, site: int):
    if not 0 <= i < len(xs): fault("E-PROOF-VIOLATED", site, f"discharged operation at {sites[site].path} violated", "")
    return xs[i]

def prim_list_concat(xs, ys): return xs + ys
def prim_list_filter(xs, keep): return tuple(x for x in xs if keep(x) is True)
def prim_list_fold(xs, init, step):
    acc = init
    for x in xs: acc = step(acc, x)
    return acc
def prim_list_map(xs, f): return tuple(f(x) for x in xs)
def prim_list_any(xs, pred): return any(pred(x) is True for x in xs)
def prim_list_all(xs, pred): return all(pred(x) is True for x in xs)
def prim_list_map2(xs, ys, f): return tuple(f(x, y) for x, y in zip(xs, ys))
def prim_list_index_of(xs, target):
    for i, x in enumerate(xs):
        if equal(x, target): return Var("", "Some", (i,))
    return V_NONE
def prim_list_nth(xs, i: int):
    if not 0 <= i < len(xs): lm_fail("OutOfRange")
    return xs[i]
def prim_list_at(xs, i: int): return Var("", "Some", (xs[i],)) if 0 <= i < len(xs) else V_NONE
def prim_list_take(xs, n: int): return xs[:max(n, 0)]
def prim_list_drop(xs, n: int): return xs[max(n, 0):]
def prim_list_sort_by(xs, less_fn):
    if len(xs) <= 1: return xs
    mid = len(xs) // 2
    a, b = prim_list_sort_by(xs[:mid], less_fn), prim_list_sort_by(xs[mid:], less_fn)
    out, i, j = [], 0, 0
    while i < len(a) and j < len(b):
        if less_fn(b[j], a[i]) is True: out.append(b[j]); j += 1
        else: out.append(a[i]); i += 1
    return tuple(out) + a[i:] + b[j:]
def prim_list_range(start: int, stop: int): return tuple(range(start, stop))
def prim_list_reverse(xs): return tuple(reversed(xs))

UPPER_TABLE = str.maketrans("abcdefghijklmnopqrstuvwxyz", "ABCDEFGHIJKLMNOPQRSTUVWXYZ")
LOWER_TABLE = str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz")
DECIMAL_RE = re.compile(r"[+-]?([0-9]+(\.[0-9]*)?|\.[0-9]+)([eE][+-]?[0-9]+)?")

TRIM_CHARS = "".join(chr(cp) for cp in (
    *range(0x09, 0x0E), *range(0x1C, 0x21), 0x85, 0xA0, 0x1680,
    *range(0x2000, 0x200B), 0x2028, 0x2029, 0x202F, 0x205F, 0x3000
))

def prim_str_concat(a: str, b: str): return a + b
def prim_str_from_int(n: int): return str(n)
def prim_str_join(parts, sep: str): return sep.join(parts)
def prim_str_length(s: str): return len(s)
def prim_str_split(s: str, sep: str): return tuple(s.split(sep)) if sep else tuple(s)
def prim_str_trim(s: str): return s.strip(TRIM_CHARS)
def prim_str_to_codes(s: str): return tuple(ord(c) for c in s)
def prim_str_from_codes(cs):
    for c in cs:
        if c < 0 or c > 0x10FFFF or (0xD800 <= c <= 0xDFFF): lm_fail("str.BadCode", c)
    return "".join(chr(c) for c in cs)
def prim_str_to_int(s: str):
    if not re.fullmatch(r"[+-]?[0-9]+", s): return V_NONE
    negative, digits = s.startswith("-"), s.lstrip("+-").lstrip("0") or "0"
    bound = "9223372036854775808" if negative else "9223372036854775807"
    if len(digits) > len(bound) or (len(digits) == len(bound) and digits > bound): return V_NONE
    val = int(digits)
    return Var("", "Some", (-val if negative else val,))
def prim_str_starts_with(s: str, prefix: str): return s.startswith(prefix)
def prim_str_contains(s: str, part: str): return part in s
def prim_str_substring(s: str, start: int, end: int):
    if not 0 <= start <= end <= len(s): lm_fail("OutOfRange")
    return s[start:end]
def prim_str_lines(s: str):
    if not s: return ()
    parts = re.split(r"\r\n|[\r\n]", s)
    if parts[-1] == "": parts.pop()
    return tuple(parts)
def prim_str_index_of(s: str, part: str):
    i = s.find(part)
    return V_NONE if i < 0 else Var("", "Some", (i,))
def prim_str_repeat(s: str, n: int): return s * max(n, 0)
def prim_str_replace(s: str, old: str, new: str): return s.replace(old, new) if old else s
def prim_str_upper_ascii(s: str): return s.translate(UPPER_TABLE)
def prim_str_lower_ascii(s: str): return s.translate(LOWER_TABLE)
def prim_str_from_float(x: float): return float_text(x)
def prim_str_to_float(s: str):
    if not DECIMAL_RE.fullmatch(s): return V_NONE
    try: v = float(s)
    except (ValueError, OverflowError): return V_NONE
    return Var("", "Some", (v + 0.0,)) if math.isfinite(v) else V_NONE

def prim_float_from_int(n: int): return float(n) + 0.0
def prim_float_sqrt(x: float):
    if x < 0.0: num_fault("E-FLOAT", "float.sqrt", [x], -1, False)
    return math.sqrt(x)
def _float_to_int(op: str, x: float, n: int) -> int:
    if not INT_MIN <= n <= INT_MAX: num_fault("E-OVERFLOW", op, [x], -1, False)
    return n
def prim_float_floor(x: float): return _float_to_int("float.floor", x, math.floor(x))
def prim_float_ceil(x: float): return _float_to_int("float.ceil", x, math.ceil(x))
def prim_float_round(x: float):
    t = math.trunc(x)
    return _float_to_int("float.round", x, t + (1 if x > 0 else -1) if abs(x - t) >= 0.5 else t)
def prim_float_trunc(x: float): return _float_to_int("float.trunc", x, math.trunc(x))

def prim_float_fixed(x: float, digits: int):
    # Exact binary ratio and unbounded integers; ties round to an even scaled integer.
    numerator, denominator = abs(x).as_integer_ratio()
    scaled, remainder = divmod(numerator * 10 ** digits, denominator)
    if remainder * 2 > denominator or (remainder * 2 == denominator and scaled % 2):
        scaled += 1
    text = str(scaled).zfill(digits + 1)
    if digits:
        text = text[:-digits] + "." + text[-digits:]
    return ("-" if x < 0 and scaled else "") + text

def sanitize_arg(a: str) -> str:
    try: return a.encode("utf-8", errors="surrogateescape").decode("utf-8", errors="replace")
    except Exception: return a

prog_args: list[str] = [sanitize_arg(a) for a in sys.argv[1:]]
out_tty = hasattr(sys.stdout, "isatty") and sys.stdout.isatty()

def prim_io_print(s: str):
    sys.stdout.write(s + "\n")
    if out_tty: sys.stdout.flush()
    return UNIT
def prim_io_eprint(s: str):
    sys.stderr.write(s + "\n"); sys.stderr.flush()
    return UNIT
def prim_io_args(): return tuple(prog_args)
def prim_io_read_line():
    sys.stdout.flush()
    try:
        source = getattr(sys.stdin, "buffer", sys.stdin)
        raw = source.readline()
        text = raw.decode("utf-8") if isinstance(raw, bytes) else raw
        if not text: return V_NONE
        if text.endswith("\n"):
            text = text[:-1]
            if text.endswith("\r"): text = text[:-1]
        return Var("", "Some", (text,))
    except (OSError, UnicodeError, ValueError) as ex: lm_fail("io.IoError", str(ex))
def prim_io_read_all():
    sys.stdout.flush()
    try:
        source = getattr(sys.stdin, "buffer", sys.stdin)
        raw = source.read()
        return raw.decode("utf-8") if isinstance(raw, bytes) else raw
    except (OSError, UnicodeError, ValueError) as ex: lm_fail("io.IoError", str(ex))

prelude_values = {
    "+": Closure(lambda a, b: add(a, b, -1), ()), "-": Closure(lambda a, b: sub(a, b, -1), ()),
    "*": Closure(lambda a, b: mul(a, b, -1), ()), "=": Closure(equal, ()),
    "!=": Closure(lambda a, b: not equal(a, b), ()), "<": Closure(less, ()),
    "<=": Closure(lambda a, b: not less(b, a), ()), ">": Closure(lambda a, b: less(b, a), ()),
    ">=": Closure(lambda a, b: not less(a, b), ()), "cons": Closure(lambda x, xs: (x,) + xs, ()),
    "pair": Closure(Pair, ()), "not": Closure(lambda a: not a, ()), "len": Closure(len, ()),
}
