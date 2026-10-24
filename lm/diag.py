"""Diagnostics: structured, JSON-line, stable codes (docs/SPEC.md section 9)."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

CODES = {
    "E-DEPS": "error",
    "E-DEP-UNFETCHED": "error",
    "E-DEP-HASH": "error",
    "E-DEP-UNPINNED": "error",
    "E-DEP-EFFECT": "error",
    "E-PARSE": "error",
    "E-SERVE": "error",
    "E-SCENARIO": "error",
    "E-NONCANONICAL": "warning",
    "E-PURPOSE-MISSING": "error",
    "E-PURPOSE-LONG": "error",
    "E-NAME-UNRESOLVED": "error",
    "E-USE-MISSING": "error",
    "E-NOT-EXPORTED": "error",
    "E-CYCLE": "error",
    "E-DUP-NAME": "error",
    "E-ARITY": "error",
    "E-TYPE": "error",
    "E-EFFECT-UNDECLARED": "error",
    "E-FAILS-UNDECLARED": "error",
    "E-MATCH-NONEXHAUSTIVE": "error",
    "E-EXAMPLE-MISSING": "error",
    "E-EXAMPLE": "error",
    "E-EXAMPLE-FAILED": "error",
    "E-REQUIRES-VIOLATED": "error",
    "E-ENSURES-VIOLATED": "error",
    "E-EFFECT-DENIED": "error",
    "E-RECURSION-LIMIT": "error",
    "E-OVERFLOW": "error",
    "E-FLOAT": "error",
    "E-CONST-BUDGET": "error",
    "E-PROOF-VIOLATED": "error",
    "E-PATTERN": "error",
    "W-USE-UNUSED": "warning",
    "W-EFFECT-UNUSED": "warning",
    "W-FAILS-UNUSED": "warning",
    "W-FOR-PURE": "warning",
}


class ExternalFile(str):
    """A cached source path retaining provenance through diagnostic creation."""


@dataclass
class Diagnostic:
    code: str
    severity: str
    file: str
    line: int
    col: int
    path: str
    msg: str
    expected: str = ""
    found: str = ""
    fix: list = field(default_factory=list)
    data: dict = field(default_factory=dict)  # code-specific structured fields; omitted when empty
    ext: bool = False

    def to_json(self) -> str:
        d = asdict(self)
        if not d["data"]:
            del d["data"]
        if not d["ext"]:
            del d["ext"]
        return json.dumps(d, ensure_ascii=False, separators=(",", ":"))


def make(code, file, line, col, msg, path="", expected="", found="", fix=None, data=None) -> Diagnostic:
    return Diagnostic(code, CODES[code], file, line, col, path, msg, expected, found,
                      fix or [], data or {}, ext=isinstance(file, ExternalFile))


def has_errors(diags) -> bool:
    return any(d.severity == "error" for d in diags)
