"""Dev-only real-tokenizer counts for S5 (ADR-051 item 5): Anthropic Messages count_tokens over stdlib urllib.

Not part of the core toolchain. Needs ANTHROPIC_API_KEY; raises TokenizerUnavailable otherwise, never
falls back to the heuristic. Framing: one user message whose content is exactly the source text; the
fixed framing overhead (a one-character message) is measured and subtracted, both numbers are kept.
"""
from __future__ import annotations

import hashlib
import json
import os
import statistics
import urllib.error
import urllib.request

MODEL = "claude-opus-5-5"
API_VERSION = "2023-06-01"
URL = "https://api.anthropic.com/v1/messages/count_tokens"
BASELINE_TEXT = "x"


class TokenizerUnavailable(RuntimeError):
    pass


def _request(text: str, key: str) -> int:
    body = json.dumps({"model": MODEL, "messages": [{"role": "user", "content": text}]}).encode()
    headers = {"x-api-key": key, "anthropic-version": API_VERSION, "content-type": "application/json"}
    req = urllib.request.Request(URL, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.load(resp)["input_tokens"]
    except urllib.error.HTTPError as e:
        raise TokenizerUnavailable(f"count_tokens HTTP {e.code}: {e.read().decode(errors='replace')[:300]}") from e
    except urllib.error.URLError as e:
        raise TokenizerUnavailable(f"count_tokens unreachable: {e.reason}") from e


class Counter:
    """Counts source texts; `count` returns (raw, net) where net = raw - framing overhead."""

    def __init__(self):
        self.key = os.environ.get("ANTHROPIC_API_KEY")
        if not self.key:
            raise TokenizerUnavailable("--tokenizer anthropic needs ANTHROPIC_API_KEY (dev-only; see bench/count_tokens.py)")
        self.baseline = _request(BASELINE_TEXT, self.key) - 1

    def count(self, text: str) -> tuple[int, int]:
        raw = _request(text, self.key)
        return raw, raw - self.baseline

    def meta(self) -> dict:
        return {"model": MODEL, "api_version": API_VERSION, "framing": "one user message = source text",
                "baseline_overhead": self.baseline}


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def task_texts(d) -> dict:
    """The three texts the heuristic S5 compares: canonical LM, full Python, bare Python."""
    from lm.bench import bare_python, lm_file, py_file
    from lm.loader import load
    from lm.printer import print_module
    py = py_file(d).read_text()
    return {"lm": print_module(load([str(d)]).modules[lm_file(d).stem].root), "py_full": py, "py_bare": bare_python(py)}


def s5_real(dirs, counter: Counter) -> dict:
    rows = []
    for d in dirs:
        row = {"task": d.name}
        for kind, text in task_texts(d).items():
            raw, net = counter.count(text)
            row[kind] = {"raw": raw, "net": net, "sha256": sha256(text)}
        rows.append(row)
    ratio = lambda kind: statistics.median(r["lm"]["net"] / r[kind]["net"] for r in rows)
    return {"meta": counter.meta(), "rows": rows, "median_vs_full": ratio("py_full"), "median_vs_bare": ratio("py_bare")}


def summary_section(res: dict) -> str:
    m = res["meta"]
    verdict = "met" if res["median_vs_full"] <= 1.3 else "OPEN (target <= 1.3x)"
    L = ["", "## S5 with the Anthropic tokenizer (ADR-051 item 5; dev-only)", "",
         f"Model `{m['model']}`, API version `{m['api_version']}`, framing: {m['framing']}; framing overhead "
         f"{m['baseline_overhead']} tokens subtracted (net). Median LM/Python: {res['median_vs_full']:.2f}x vs full Python "
         f"({verdict}); {res['median_vs_bare']:.2f}x vs bare Python.", "",
         "| task | LM net | Python full net | Python bare net |", "|---|---|---|---|"]
    L += [f"| {r['task']} | {r['lm']['net']} | {r['py_full']['net']} | {r['py_bare']['net']} |" for r in res["rows"]]
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    import sys
    c = Counter()
    for path in sys.argv[1:]:
        src = open(path, encoding="utf-8").read()
        print(path, *c.count(src), sha256(src)[:12])
