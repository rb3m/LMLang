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
    ("add-ext", "STEM", "opt in to a toolchain extension in lm.deps"),
    ("add-example", "SYM FORM", "add an example"),
    ("replace-ref", "NODE-PATH NEW",
     "replace one name atom at a diagnostic path"),
    ("apply", "JSON", "apply a diagnostic fix object or list "
     "(add-use/remove-use/add-eff/add-fails/add-ext/replace-ref/fmt)"),
)

COMMAND_DETAILS = {
    "fetch": (
        "  Pins store a SHA-256 in lm.deps. Pinned modules are pure by default.\n"
        "  For E-DEP-EFFECT, review bodies and get owner approval before re-pinning\n"
        "  with --allow EFF. proc.run is forbidden, as is combining net.http with\n"
        "  fs.read or env.read. For E-DEP-UNFETCHED or E-DEP-HASH, run lm fetch.\n"
        "  To publish, serve one canonical, stdlib-only STEM.lm at a stable direct\n"
        "  HTTPS URL. Use a new URL for each version.\n"
    ),
    "serve": (
        "  Use a named handler with (sig (req http.Request) -> http.Response)\n"
        "  and no declared failures. Pass --allow EFF for each declared effect.\n"
        "  To build, use lm build --serve MOD.FN --target py|go. Built handlers\n"
        "  use CGI by default and accept --listen for listener mode.\n"
    ),
    "test": (
        "  Script subprocess examples with ordered clauses in given:\n"
        "    (proc (argv S...) (stdin S)? (cwd S)? (env K V)* OUTCOME)\n"
        "  Outcomes: (exited N (stdout S)? (stderr S)?), (signaled N),\n"
        "  or (error \"category\"). Requests match exactly, including env order.\n"
    ),
}


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
    sys.stdout.write(COMMAND_DETAILS.get(command.name, ""))
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
