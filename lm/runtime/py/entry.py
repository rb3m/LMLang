"""Entry, diagnostics and seed handling for `lm build --target py` programs (ADR-062); embedded after rt.py."""

DIAG_KEYS = ("code", "severity", "file", "line", "col", "path", "msg", "expected", "found", "fix", "data")
random_seed = None

def diag_json(d: dict) -> str:
    """Serialize a diagnostic exactly like lm/diag.py and the Go runtime: field order, compact, data only if set."""
    out = {k: d.get(k, [] if k == "fix" else {} if k == "data" else "") for k in DIAG_KEYS}
    if not out["data"]:
        del out["data"]
    return json.dumps(out, ensure_ascii=False, separators=(",", ":"))

def parse_seed(s: str):
    sign, digits = ("", s)
    if digits[:1] in ("+", "-"):
        sign, digits = digits[:1], digits[1:]
    if not digits or digits.strip("0123456789"):
        return None
    v = int(sign + digits)
    return v if -(2 ** 63) <= v < 2 ** 63 else None

def seed_from_env():
    """Validate LM_SEED before running the entry, like Go binaries: malformed is a usage error (exit 3)."""
    global random_seed
    s = os.environ.get("LM_SEED")
    if s is None:
        return
    random_seed = parse_seed(s)
    if random_seed is None:
        sys.stderr.write("LM_SEED must be a signed 64-bit decimal integer\n"); sys.exit(3)

def run_main(entry, site: int):
    seed_from_env()
    box: dict = {}
    def target():
        try: box["r"] = entry()
        except LmFail as fl: box["fail"] = fl
        except Fault as ft: box["fault"] = ft
        except RecursionError:
            box["fault"] = Fault({"code": "E-RECURSION-LIMIT", "severity": "error", "file": "",
                                  "line": 1, "col": 1, "path": "",
                                  "msg": f"recursion limit reached ({max_depth} nested calls)",
                                  "expected": "", "found": "", "fix": []})
        except BaseException as ex: box["ex"] = ex
    try:
        threading.stack_size(64 * 1024 * 1024); sys.setrecursionlimit(550000)
    except (ValueError, RuntimeError): pass
    t = threading.Thread(target=target); t.start(); t.join()
    try: sys.stdout.flush()
    except Exception: pass
    if "ex" in box: raise box["ex"]
    if "fail" in box:
        sys.stderr.write(str(box["fail"]) + "\n"); sys.exit(1)
    if "fault" in box:
        sys.stderr.write(diag_json(box["fault"].diag) + "\n"); sys.exit(70)
    val = box.get("r")
    if isinstance(val, int) and type(val) is not bool:
        if not 0 <= val <= 255:
            d = {"code": "E-EXIT-RANGE", "severity": "error", "file": "", "line": 1, "col": 1, "path": "",
                 "msg": f"exit status {val} is outside 0-255", "expected": "", "found": show(val), "fix": []}
            if site >= 0:
                s = sites[site]
                d["file"], d["line"], d["col"], d["path"] = s.file, s.line, s.col, s.path
            sys.stderr.write(diag_json(d) + "\n"); sys.exit(70)
        sys.exit(val)
    sys.exit(0)

def run_cases(cases):
    seed_from_env()
    try:
        threading.stack_size(64 * 1024 * 1024); sys.setrecursionlimit(550000)
    except (ValueError, RuntimeError): pass
    def run_one(fn):
        try: return "ok", show(fn())
        except LmFail as fl: return "fail", str(fl)
        except Fault as ft: return "fault", ft.diag["code"]
        except RecursionError: return "fault", "E-RECURSION-LIMIT"
    def target():
        for label, fn in cases:
            global depth
            depth = 0
            if "reset_rng" in globals(): reset_rng()
            kind, detail = run_one(fn)
            sys.stdout.write(f"{label}\t{kind}\t{detail}\n")
        sys.stdout.flush()
    t = threading.Thread(target=target); t.start(); t.join()
