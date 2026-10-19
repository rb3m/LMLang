"""Mechanical runtime code embedding from real lm/ sources for Python target (ADR-062)."""
from __future__ import annotations

from pathlib import Path
from . import ir

LM_DIR = Path(__file__).resolve().parent

FLOAT_MATH_PRIMS = frozenset([
    "float.sinh", "float.cosh", "float.tanh", "float.log1p", "float.expm1",
    "float.asin", "float.acos", "float.atan", "float.atan2", "float.sin",
    "float.cos", "float.tan", "float.pow", "float.cbrt", "float.hypot",
    "float.pi", "float.e", "float.exp", "float.ln", "float.log2", "float.log10",
])

# Topological ordering of float math modules
ALL_FLOAT_MODULES = [
    "float_math.py",
    "float_math_reduce.py",
    "float_math_m1.py",
    "float_math_hyp.py",
    "float_math_atrig.py",
    "float_math_trig.py",
    "float_math_roots.py",
    "float_math_pow.py",
]

MODULE_FOR_PRIM = {
    "float.pi": ["float_math.py"],
    "float.e": ["float_math.py"],
    "float.exp": ["float_math.py"],
    "float.ln": ["float_math.py"],
    "float.log2": ["float_math.py"],
    "float.log10": ["float_math.py"],
    "float.log1p": ["float_math.py", "float_math_m1.py"],
    "float.expm1": ["float_math.py", "float_math_m1.py"],
    "float.sinh": ["float_math.py", "float_math_m1.py", "float_math_hyp.py"],
    "float.cosh": ["float_math.py", "float_math_m1.py", "float_math_hyp.py"],
    "float.tanh": ["float_math.py", "float_math_m1.py", "float_math_hyp.py"],
    "float.asin": ["float_math.py", "float_math_reduce.py", "float_math_atrig.py"],
    "float.acos": ["float_math.py", "float_math_reduce.py", "float_math_atrig.py"],
    "float.atan": ["float_math.py", "float_math_reduce.py", "float_math_atrig.py"],
    "float.atan2": ["float_math.py", "float_math_reduce.py", "float_math_atrig.py"],
    "float.sin": ["float_math.py", "float_math_reduce.py", "float_math_trig.py"],
    "float.cos": ["float_math.py", "float_math_reduce.py", "float_math_trig.py"],
    "float.tan": ["float_math.py", "float_math_reduce.py", "float_math_trig.py"],
    "float.cbrt": ["float_math.py", "float_math_roots.py"],
    "float.hypot": ["float_math.py", "float_math_roots.py"],
    "float.pow": ["float_math_pow.py"],
}

FLOAT_PRIM_DEFS = {
    "float.pi": "def prim_float_pi(): return PI",
    "float.e": "def prim_float_e(): return E",
    "float.exp": 'prim_float_exp = float_math_prim("float.exp", exp)',
    "float.ln": 'prim_float_ln = float_math_prim("float.ln", ln, positive=True)',
    "float.log2": 'prim_float_log2 = float_math_prim("float.log2", log2, positive=True)',
    "float.log10": 'prim_float_log10 = float_math_prim("float.log10", log10, positive=True)',
    "float.sinh": 'prim_float_sinh = float_math_prim("float.sinh", sinh)',
    "float.cosh": 'prim_float_cosh = float_math_prim("float.cosh", cosh)',
    "float.tanh": 'prim_float_tanh = float_math_prim("float.tanh", tanh)',
    "float.log1p": 'prim_float_log1p = float_math_prim("float.log1p", log1p)',
    "float.expm1": 'prim_float_expm1 = float_math_prim("float.expm1", expm1)',
    "float.asin": 'prim_float_asin = float_math_prim("float.asin", asin)',
    "float.acos": 'prim_float_acos = float_math_prim("float.acos", acos)',
    "float.atan": 'prim_float_atan = float_math_prim("float.atan", atan)',
    "float.atan2": 'prim_float_atan2 = float_math_prim("float.atan2", atan2)',
    "float.sin": 'prim_float_sin = float_math_prim("float.sin", sin)',
    "float.cos": 'prim_float_cos = float_math_prim("float.cos", cos)',
    "float.tan": 'prim_float_tan = float_math_prim("float.tan", tan)',
    "float.cbrt": 'prim_float_cbrt = float_math_prim("float.cbrt", cbrt)',
    "float.hypot": 'prim_float_hypot = float_math_prim("float.hypot", hypot)',
    "float.pow": 'prim_float_pow = float_math_prim("float.pow", pow)',
}


def clean_source(text: str) -> str:
    lines = []
    for line in text.splitlines():
        trimmed = line.strip()
        if trimmed.startswith("from .") or trimmed.startswith("from __future__"):
            continue
        lines.append(line)
    return "\n".join(lines)


def wrap_module(text: str, ns_name: str) -> str:
    cleaned = clean_source(text)
    indented = "\n".join(("\t" + l if l.strip() else "") for l in cleaned.splitlines())
    return (
        f"def _make_{ns_name}():\n"
        f"{indented}\n"
        f"\tclass _Mod: pass\n"
        f"\t_m = _Mod()\n"
        f"\tfor _k, _v in list(locals().items()):\n"
        f"\t\tif not _k.startswith('_make_'): setattr(_m, _k, _v)\n"
        f"\treturn _m\n"
        f"{ns_name} = _make_{ns_name}()\n"
    )


def _has_map_set(e) -> bool:
    if isinstance(e, (ir.MapLit, ir.SetLit)):
        return True
    return any(_has_map_set(c) for c in ir.children(e))


def has_map_set(prog: ir.Program) -> bool:
    for p in prog.prims:
        if p.startswith("coll.") or p.startswith("map.") or p.startswith("set.") or p.startswith("json."):
            return True
    for f in prog.fns.values():
        if f.body is not None and _has_map_set(f.body):
            return True
    for c in prog.consts.values():
        if _has_map_set(c.expr):
            return True
    for ctor in prog.ctors:
        if ctor.startswith("json."):
            return True
    return False


def needed_float_prims(prog: ir.Program) -> set[str]:
    return set(prog.prims) & FLOAT_MATH_PRIMS


def needed_float_modules(prog: ir.Program) -> list[str]:
    needed = set()
    for p in needed_float_prims(prog):
        needed.update(MODULE_FOR_PRIM.get(p, []))
    return [m for m in ALL_FLOAT_MODULES if m in needed]


def has_rand(prog: ir.Program) -> bool:
    return any(p.startswith("rand.") for p in prog.prims)


def has_json(prog: ir.Program) -> bool:
    return any(p.startswith("json.") for p in prog.prims) or any(c.startswith("json.") for c in prog.ctors)


def has_fs(prog: ir.Program) -> bool:
    return any(p.startswith(("fs.", "env.")) for p in prog.prims)


def has_time(prog: ir.Program) -> bool:
    return any(p.startswith("time.") for p in prog.prims)


def has_unicode_casing(prog: ir.Program) -> bool:
    return "str.upper" in prog.prims or "str.lower" in prog.prims


UNICODE_CASING_HELPERS = """def prim_str_upper(s: str): return to_upper_str(s)
def prim_str_lower(s: str): return to_lower_str(s)
"""


MAP_SET_HELPERS = """class tree:
\tK, V, L, R, H, N = range(6)
\theight = staticmethod(height)
\tsize = staticmethod(size)
\tnode = staticmethod(node)
\tbalance = staticmethod(balance)
\tinsert = staticmethod(insert)
\tfind = staticmethod(find)
\tremove = staticmethod(remove)
\titems = staticmethod(items)
\tColl = Coll
\tbuild = staticmethod(build)

def prim_map_put(m, k, v): return coll.put(_it, m, k, v)
def prim_map_at(m, k): return coll.at(_it, m, k)
def prim_map_has(m, k): return coll.has(_it, m, k)
def prim_map_remove(m, k): return coll.remove(_it, m, k)
def prim_map_size(m): return coll.size(_it, m)
def prim_map_keys(m): return coll.keys(_it, m)
def prim_map_values(m): return coll.values(_it, m)
def prim_map_fold(m, init, step): return coll.map_fold(_it, m, init, step)
def prim_map_to_list(m): return coll.to_list(_it, m)
def prim_map_from_list(ps): return coll.from_list(_it, ps)

def prim_set_add(s, x): return coll.add(_it, s, x)
def prim_set_has(s, x): return coll.has(_it, s, x)
def prim_set_remove(s, x): return coll.remove(_it, s, x)
def prim_set_size(s): return coll.size(_it, s)
def prim_set_to_list(s): return coll.keys(_it, s)
def prim_set_fold(s, init, step): return coll.set_fold(_it, s, init, step)
def prim_set_union(s, t): return coll.union(_it, s, t)
def prim_set_intersect(s, t): return coll.intersect(_it, s, t)
def prim_set_diff(s, t): return coll.diff(_it, s, t)

def map_of(keys, vals):
\troot = None
\tfor k, v in zip(keys, vals): root = insert(root, k, v)
\treturn Coll(root, False)

def set_of(elems):
\troot = None
\tfor k in elems: root = insert(root, k, UNIT)
\treturn Coll(root, True)

def show_coll(v) -> str:
\tif v.is_set:
\t\treturn "(setof" + "".join(" " + show(k) for k, _ in items(v.root)) + ")"
\treturn "(mapof" + "".join(f" ({show(k)} {show(x)})" for k, x in items(v.root)) + ")"
"""

FLOAT_MATH_WRAPPER = """def float_math_prim(op: str, fn, positive: bool = False):
\tdef checked(*args):
\t\tif positive and args[0] <= 0.0:
\t\t\tnum_fault("E-FLOAT", op, list(args), -1, False)
\t\ttry:
\t\t\tr = fn(*args)
\t\texcept (OverflowError, ValueError, ZeroDivisionError):
\t\t\tnum_fault("E-FLOAT", op, list(args), -1, False)
\t\tif not math.isfinite(r):
\t\t\tnum_fault("E-FLOAT", op, list(args), -1, False)
\t\treturn r + 0.0
\treturn checked
"""

RAND_HELPERS = """_rng = None
def get_rng():
\tglobal _rng
\tif _rng is None:
\t\t_rng = SplitMix64(random_seed)
\treturn _rng

def reset_rng():
\tglobal _rng
\t_rng = SplitMix64(0 if random_seed is None else random_seed)

def prim_rand_int(lo: int, hi: int): return get_rng().int(lo, hi)
def prim_rand_float(): return get_rng().float()
"""

JSON_HELPERS = """def prim_json_parse(s: str): return json_mod.parse(_it, s)
def prim_json_print(j): return json_mod.print_json(_it, j)
"""

FS_HELPERS = """def prim_fs_read(path: str): return io_mod.fs_read(_it, path)
def prim_fs_write(path: str, text: str): return io_mod.fs_write(_it, path, text)
def prim_fs_exists(path: str): return io_mod.fs_exists(_it, path)
def prim_env_lookup(name: str): return io_mod.env_lookup(_it, name)
def prim_fs_append(path: str, text: str): return io_mod.fs_append(_it, path, text)
def prim_fs_entries(path: str): return io_mod.fs_entries(_it, path)
def prim_fs_is_dir(path: str): return io_mod.fs_is_dir(_it, path)
def prim_fs_make_dir(path: str): return io_mod.fs_make_dir(_it, path)
def prim_fs_remove(path: str): return io_mod.fs_remove(_it, path)
def prim_fs_rename(source: str, target: str): return io_mod.fs_rename(_it, source, target)
"""

TIME_HELPERS = """def prim_time_now_ms(): return time.time_ns() // 1_000_000
def prim_time_mono_ms(): return time.monotonic_ns() // 1_000_000
"""


def generate_embedded_runtime(prog: ir.Program) -> str:
    parts = [
        "class _It:",
        "\t@staticmethod",
        "\tdef apply(f, args): return f(*args)",
        "_it = _It()",
        "",
    ]

    if has_map_set(prog):
        tree_src = clean_source((LM_DIR / "tree.py").read_text(encoding="utf-8"))
        coll_src = (LM_DIR / "coll_prims.py").read_text(encoding="utf-8")
        parts.extend([
            "# --- Embedded Map/Set runtime (from lm/tree.py, lm/coll_prims.py) ---",
            tree_src,
            "",
            MAP_SET_HELPERS,
            "",
            wrap_module(coll_src, "coll"),
            "",
        ])

    float_mods = needed_float_modules(prog)
    if float_mods:
        parts.append("# --- Embedded Float Math runtime (from lm/float_math*.py) ---")
        for m in float_mods:
            src = clean_source((LM_DIR / m).read_text(encoding="utf-8"))
            parts.extend([src, ""])
        parts.extend([FLOAT_MATH_WRAPPER, ""])
        for p in sorted(needed_float_prims(prog)):
            parts.append(FLOAT_PRIM_DEFS[p])
        parts.append("")

    if has_rand(prog):
        rand_src = clean_source((LM_DIR / "rand_prims.py").read_text(encoding="utf-8"))
        parts.extend([
            "# --- Embedded Rand runtime (from lm/rand_prims.py) ---",
            rand_src,
            "",
            RAND_HELPERS,
            "",
        ])

    if has_json(prog):
        json_src = (LM_DIR / "json_prims.py").read_text(encoding="utf-8")
        parts.extend([
            "# --- Embedded JSON runtime (from lm/json_prims.py) ---",
            wrap_module(json_src, "json_mod"),
            "",
            JSON_HELPERS,
            "",
        ])

    if 'http.request' in prog.prims:
        http_src = (LM_DIR / 'http_prims.py').read_text(encoding='utf-8')
        parts.extend([
            '# --- Embedded HTTP runtime (from lm/http_prims.py) ---',
            wrap_module(http_src, 'http_mod'),
            'def prim_http_request(method, url, headers, body):',
            '    return http_mod.http_request(None, method, url, headers, body)',
            '',
        ])

    if has_fs(prog):
        fs_src = (LM_DIR / "io_prims.py").read_text(encoding="utf-8")
        parts.extend([
            "# --- Embedded FS runtime (from lm/io_prims.py) ---",
            wrap_module(fs_src, "io_mod"),
            "",
            FS_HELPERS,
            "",
        ])

    if has_time(prog):
        parts.extend([
            "# --- Time runtime ---",
            TIME_HELPERS,
            "",
        ])

    if has_unicode_casing(prog):
        uni_src = clean_source((LM_DIR / "unicode_tables.py").read_text(encoding="utf-8"))
        parts.extend([
            "# --- Embedded Unicode tables (from lm/unicode_tables.py) ---",
            uni_src,
            "",
            UNICODE_CASING_HELPERS,
            "",
        ])

    return "\n".join(parts)
