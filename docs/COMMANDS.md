# `lm` commands

Run as `lm ...` via `bin/lm`, or `python3 -m lm ...` (Python >= 3.10; older interpreters exit 3 with a message; `LM_PYTHON` picks one). Read the line for a command before using an unfamiliar flag. Edit op details are in docs/SPEC.md section 15, build details in section 16.

## Help
- `help [CMD]`, `--help`, `-h`: print usage, or one command's synopsis and summary; `help edit` also lists operations.
- `guide`: print the bundled syntax, workflow and scenario guide.
- `--version`, `-V`: print `lm` and its version.
- Help and version exit 0; no arguments or an unknown command exit 3 and print usage to stderr.

## Project
- `new DIR`: scaffold a project that passes the gate.
- `fmt [--check] [--stdout] [PATH..]`
- `check [PATH..]`: defaults to src, examples; stdlib always loadable. Without PATH arguments, also validates tests/accept/*.accept statically, reporting E-SCENARIO errors without executing scenarios.
- `test [PATH..]`: check, then run all examples.
- `run MOD.FN 'LM-expr'.. [--seed N] [--allow EFF] [--no-contracts] [-- PROGRAM-ARGS..]`: prints the return value (an entry's Int status too) and exits 0; a built binary exits with the returned Int. `--allow` accepts `io.out io.in env.read fs.read fs.write fs.delete net.http time.now rand` (repeat the flag for multiple effects). All diagnostics, including static check warnings/errors and `<arg>` parse/type errors, go to stderr; stdout contains only program output and the printed result.
- `serve MOD.FN [PATH..] [--cgi] [--host H] [--port N] [--public] [--allow EFF]..`: serve a named HTTP handler; default loopback listener 127.0.0.1:8080, port 0 chooses a free port; `--cgi` reads one CGI request. Non-loopback binds require `--public` (usage exit 2). See SPEC 8 and DEPLOY-CGI.md.
- `build [--serve] MOD.FN [PATH..] [-o OUT] [--target go|py] [--os linux|darwin] [--arch amd64|arm64] [--no-contracts] [--keep-go DIR]`: ordinary entry has no params and returns Unit or Int exit status; `--serve` instead selects a named `http.Request -> http.Response` handler with no declared `fails` (E-SERVE otherwise), emitting CGI by default with optional built `--listen [--host H] [--port N] [--public]`; default target is `go` (needs `go` on PATH or `$LM_GO`). Target `py` emits a standalone executable Python script (`<fn>.py` by default) with no external compiler requirement; `--os`, `--arch`, `--keep-go` are rejected with `--target py`.
- `bench [--tokenizer anthropic] | bench --project PATH [--json]`: without `--project`, writes bench/results/summary.md; tasks in bench/tasks (optional `--tokenizer anthropic` adds a dev-only real-tokenizer S5 via bench/count_tokens.py, needs ANTHROPIC_API_KEY, never falls back). With `--project PATH`, measures S1 and S2 on the project at PATH without overwriting bench/results/, outputting a markdown table plus JSON (or JSON only with `--json`).

## Queries
- `index [PATH..] [--stdlib] [--exported] [--modules | --module M]`: one line per symbol. `--stdlib --modules` prints one line per stdlib module: `MODULE  N exports  PURPOSE`. `--stdlib --module M` prints only M's symbols in the usual format. `--modules` and `--module` require `--stdlib`, are mutually exclusive, and reject PATH arguments (exit 3). An unknown M exits 3 and lists stdlib modules on stderr. Bare `--stdlib` output is unchanged.
- `slice SYM [--bodies --depth N --budget T]`: root + callee signatures + type closure.
- `callers SYM [PATH..]`, `deps SYM [--depth N]`, `hash SYM`
- `explain SYM`: human-readable summary.

## Editing
- `edit OP ARGS.. [--in PATH].. [--dry-run] [--force]` (`--force` lets `remove-decl`/`remove-fn` remove a function or const that still has references, or `rename` rewrite scenarios mentioning a renamed variant). Ops: replace-body replace-decl add-decl remove-decl remove-fn rename set-purpose set-sig add-use remove-use add-export add-eff add-fails add-example replace-ref apply (table in docs/SPEC.md section 15).

## Acceptance
- `accept [--review|--guard|--bless] [--approve DIGEST.. --by "TEXT"] [--retire NAME.. --by "TEXT"] [--dir D] [--lock F]`: scenarios in tests/accept (`--dir`), lock file accept.lock (`--lock`), file format in docs/TESTING.md "Acceptance scenarios". `--approve` records owner approval (non-interactive); `--retire` drops the lock lines of renamed or deleted scenarios on the owner's word (refuses names still present or not locked); `--bless` is human-interactive.

## Exit codes
0 ok / 1 errors or LM failure / 2 toolchain bug / 3 usage / 70 runtime fault (E-OVERFLOW, E-RECURSION-LIMIT, contract violation).

## Public export
- `scripts/export-public.sh DEST [--scan-only]`: export a clean HEAD without private environment details, or scan the current tracked public files; never commits or pushes.
