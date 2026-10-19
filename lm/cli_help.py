"""Help and the bundled agent guide."""
from __future__ import annotations

import sys
from pathlib import Path

from .commands import COMMANDS, USAGE, command_help

# Compact rendering of SPEC section 15; keep the operation names in sync.
EDIT_OPS = (
    ("replace-body", "SYM EXPR", "replace a function body"),
    ("replace-decl", "SYM FORM", "replace a declaration; name must match"),
    ("add-decl", "MODULE FORM", "add a function, const, type or error"),
    ("remove-decl", "SYM [--force]",
     "delete fn/const and export; refuse references"),
    ("remove-fn", "SYM [--force]", "alias for remove-decl"),
    ("rename", "SYM NEW [--force]",
     "rename definition, export and references; roll back new errors; "
     "variant scenarios require --force and become proposed"),
    ("set-purpose", "SYM or MODULE, TEXT", "set purpose text"),
    ("set-sig", "SYM (sig ..)", "set signature and re-check callers"),
    ("add-use", "MODULE NAME", "add use idempotently"),
    ("remove-use", "MODULE NAME", "remove use idempotently"),
    ("add-export", "MODULE NAME", "add export idempotently"),
    ("add-eff", "SYM NAME",
     "add effect idempotently; create clause if needed"),
    ("add-fails", "SYM NAME",
     "add failure idempotently; create clause if needed"),
    ("add-example", "SYM FORM", "add an example"),
    ("replace-ref", "NODE-PATH NEW",
     "replace one name atom at a diagnostic path"),
    ("apply", "JSON", "apply a diagnostic fix object or list "
     "(add-use/remove-use/add-eff/add-fails/replace-ref/fmt)"),
)


def unknown_command(name: str) -> int:
    sys.stderr.write(f"lm: unknown command `{name}`\n{USAGE}")
    return 3


def cmd_help(args) -> int:
    if not args:
        sys.stdout.write(USAGE)
        return 0
    if len(args) != 1:
        sys.stderr.write("usage: lm help [CMD]\n")
        return 3
    command = COMMANDS.get(args[0])
    if command is None:
        return unknown_command(args[0])
    sys.stdout.write(command_help(command))
    if command.name == "edit":
        print("  op | args | effect")
        for op, arguments, effect in EDIT_OPS:
            print(f"  {op} | {arguments} | {effect}")
    return 0


def cmd_guide(args) -> int:
    if args:
        sys.stderr.write("usage: lm guide\n")
        return 3
    sys.stdout.write((Path(__file__).parent / "guide.md").read_text(
        encoding="utf-8"))
    return 0
