"""Measure S1 and S2 on a project directory (ADR-064)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from .bench import s1_s2
from .loader import _scan


def bench_project(path: str | Path) -> dict | None:
    p = Path(path)
    if not p.is_dir():
        return None
    src_dir = p / "src" if (p / "src").is_dir() else p
    files = _scan(src_dir, True)
    if not files:
        return None
    res = s1_s2([src_dir])
    res["project"] = str(path)
    res["modules"] = len(files)
    res["total_tokens"] = res["whole_tokens"]
    return res


def format_markdown_table(res: dict) -> str:
    rows = [
        ("Project", res["project"]),
        ("Modules", str(res["modules"])),
        ("Functions", str(res["functions"])),
        ("Total tokens", str(res["total_tokens"])),
        ("S1 slice vs project text", f"{res['s1_median']:.1%} (median), {res['s1_max']:.1%} (max)"),
        ("S1 slice vs module text", f"{res['s1_module_median']:.1%} (median), {res['s1_module_max']:.1%} (max)"),
        ("S2 edit op vs module text", f"{res['s2_median']:.1%} (median), {res['s2_max']:.1%} (max)"),
    ]
    lines = ["| Metric | Value |", "|---|---|"]
    lines += [f"| {k} | {v} |" for k, v in rows]
    return "\n".join(lines)


def cmd_bench_project(args: list[str]) -> int:
    to_json = "--json" in args
    rest = [a for a in args if a != "--json"]
    if len(rest) != 2 or rest[0] != "--project":
        sys.stderr.write("usage: lm bench --project PATH [--json]\n")
        return 3
    path_str = rest[1]
    res = bench_project(path_str)
    if res is None:
        sys.stderr.write(f"lm bench: bad project path: {path_str}\n")
        return 3
    json_str = json.dumps(res, indent=2)
    if to_json:
        sys.stdout.write(json_str + "\n")
    else:
        sys.stdout.write(format_markdown_table(res) + "\n\n" + json_str + "\n")
    return 0
