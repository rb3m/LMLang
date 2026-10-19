"""Command dispatch. Exit codes: 0 ok, 1 error diagnostics or LM failure, 2 toolchain bug, 3 usage, 70 runtime fault."""
from __future__ import annotations

import sys
import traceback
from importlib import import_module

from .cli_common import USAGE, _report, _static
from .commands import COMMANDS


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        sys.stderr.write(USAGE)
        return 3
    cmd, rest = argv[0], argv[1:]
    try:
        if cmd in ("--help", "-h"):
            cmd = "help"
        if cmd in ("--version", "-V"):
            if rest:
                sys.stderr.write(USAGE)
                return 3
            from . import __version__
            print(f"lm {__version__}")
            return 0
        command = COMMANDS.get(cmd)
        if command is None:
            from .cli_help import unknown_command
            return unknown_command(cmd)
        module, function = command.handler.split(":")
        handler = getattr(import_module(module), function)
        if cmd == "build":
            return handler(rest, _static, _report)
        return handler(rest)
    except Exception:  # toolchain bug, not a user-program fault
        traceback.print_exc()
        return 2
