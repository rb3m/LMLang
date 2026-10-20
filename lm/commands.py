"""Command metadata shared by dispatch and help; handlers load on demand."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Command:
    name: str
    synopsis: str
    summary: str
    handler: str


COMMANDS = {
    command.name: command for command in (
        Command("fmt", "fmt [--check] [--stdout] [PATH..]",
                "Format modules canonically.", "lm.cli_project:cmd_fmt"),
        Command("check", "check [PATH..]",
                "Check names, types, contracts and effects.",
                "lm.cli_project:cmd_check"),
        Command("test", "test [PATH..]", "Check and run every example.",
                "lm.cli_project:cmd_test"),
        Command("run", "run MOD.FN [ARG..] [--seed N] [--allow EFF] "
                "[--no-contracts] [-- PROGRAM-ARGS..]",
                "Interpret a function with explicit effect permissions; prints its "
                "return value and exits 0 (use build for a real exit status).",
                "lm.cli_run:cmd_run"),
        Command("serve", "serve MOD.FN [PATH..] [--cgi] [--port N] [--host H] "
                "[--public] [--allow EFF]..",
                "Serve an HTTP handler using CGI or a sequential listener.",
                "lm.cli_serve:cmd_serve"),
        Command("build", "build [--serve] MOD.FN [PATH..] [-o OUT] [--target go|py] "
                "[--os linux|darwin] [--arch amd64|arm64] [--no-contracts] "
                "[--keep-go DIR]", "Build a native binary or Python script.",
                "lm.build:cmd_build"),
        Command("edit", "edit OP ARGS.. [--in PATH].. [--dry-run] [--force]",
                "Edit the AST by operation; see lm help edit for ops.",
                "lm.cli_edit:cmd_edit"),
        Command("explain", "explain SYM", "Explain a symbol's contract.",
                "lm.cli_query:cmd_explain"),
        Command("accept", "accept [--review] [--guard] [--bless] "
                "[--approve DIGEST.. --by TEXT] [--retire NAME.. --by TEXT] "
                "[--dir D] [--lock F]",
                "Review and check human-owned scenarios.",
                "lm.cli_accept:cmd_accept"),
        Command("bench", "bench [--tokenizer anthropic] | "
                "bench --project PATH [--json]", "Measure toolchain metrics.",
                "lm.cli_project:cmd_bench"),
        Command("index", "index [PATH..] [--stdlib] [--exported] "
                "[--modules | --module M]",
                "List module symbols and signatures.",
                "lm.cli_query:cmd_index"),
        Command("slice", "slice SYM [--bodies] [--depth N] [--budget N]",
                "Show a dependency-closed symbol slice.",
                "lm.cli_query:cmd_slice"),
        Command("callers", "callers SYM [PATH..]", "List symbol references.",
                "lm.cli_query:cmd_callers"),
        Command("deps", "deps SYM [--depth N]", "List symbol dependencies.",
                "lm.cli_query:cmd_deps"),
        Command("hash", "hash SYM", "Print a symbol's content hash.",
                "lm.cli_query:cmd_hash"),
        Command("new", "new DIR",
                "Scaffold an LM project and agent instructions.",
                "lm.cli_new:cmd_new"),
        Command("guide", "guide", "Print the syntax and workflow guide.",
                "lm.cli_help:cmd_guide"),
        Command("help", "help [CMD]", "Show usage or help for one command.",
                "lm.cli_help:cmd_help"),
    )
}

EXIT_CODES = (
    "exit codes: 0 ok / 1 errors or LM failure / 2 toolchain bug / "
    "3 usage / 70 runtime fault\n"
)


def command_help(command: Command) -> str:
    return f"  lm {command.synopsis}\n    {command.summary}\n"


USAGE = (
    "usage: lm COMMAND (or python3 -m lm COMMAND)\n"
    + "".join(command_help(command) for command in COMMANDS.values())
    + "  lm --help | -h\n  lm --version | -V\n"
    + EXIT_CODES
)
