# `lm` commands

Run as `lm ...` via `bin/lm`, or `python3 -m lm ...` (Python >= 3.10; older interpreters exit 3 with a message; `LM_PYTHON` picks one). Read the line for a command before using an unfamiliar flag. Edit op details are in docs/SPEC.md section 15, build details in section 16.

## Help
- `help [CMD]`, `--help`, `-h`: print usage, or one command's synopsis and summary; `help edit` also lists operations.
- `guide`: print the bundled syntax, workflow and scenario guide.
- `--version`, `-V`: print `lm` and its version.
- Help and version exit 0; no arguments or an unknown command exit 3 and print usage to stderr.

## Project
- `new DIR`: scaffold a project that passes the gate.
- `install [--bin DIR] [--uninstall]`: link `lm` to this checkout's `bin/lm` in `~/.local/bin` (or DIR), and link `lm` to `skills/lm` in `~/.claude/skills`, `~/.agents/skills`, `~/.gemini/skills` when the corresponding agent root (`~/.claude`, `~/.codex`, `~/.gemini`) exists. Prints `linked`, `ok`, or `conflict` per link; absent agents print `skip`. Conflicts are untouched. `--uninstall` prints `removed`, `absent`, or `conflict`, removing only this checkout's links. Warns if the bin dir is off PATH when installing. Exits 0 on success, 1 on conflict or OS error, 3 on usage error. See ADR-080.
- `fetch [--pin STEM URL [--allow EFF]..]`: read `lm.deps` in the current directory and fetch missing or invalid pins into `$LM_CACHE/<sha256>/<stem>.lm` (default `~/.cache/lm`). HTTPS only, verified TLS, no redirects, status 200, 8 MiB maximum; exact bytes must match the pin before an atomic cache write. Never parses or runs downloaded code. Plain fetch prints one JSON line per pin (`stem`, `status`: `cached|fetched|error`, `msg`); exits 0 if all succeed, 1 otherwise. `--pin` explicitly trusts a download, computes its SHA-256, adds/replaces its pin, writes the requested allowance sorted by effect name (default pure), preserves other pins' allowances, rewrites `lm.deps` canonically sorted by stem, caches the bytes and prints the pin line. Check/test/run/build load only verified pins and never fetch automatically. Diagnostics: E-DEPS for invalid declarations, E-DEP-UNFETCHED/E-DEP-HASH at a pin with a fetch fix, E-DUP-NAME for collisions, E-DEP-UNPINNED at every non-stdlib external use (including other pins and unused uses), E-DEP-EFFECT at the pin for a function's unallowed declared effect, `proc.run` allowance, or `net.http` combined with `fs.read` or `env.read`. Allowances require known, unique, sorted effect names (E-DEPS otherwise). Diagnostics in external cache files include `"ext": true`.
- `fmt [--check] [--stdout] [PATH..]`
- `check [PATH..]`: defaults to src, examples; stdlib always loadable. Without PATH arguments, also validates tests/accept/*.accept statically, reporting E-SCENARIO errors without executing scenarios.
- `test [PATH..]`: check, then run project examples; examples in external modules are excluded.
- `run MOD.FN 'LM-expr'.. [--seed N] [--allow EFF] [--no-contracts] [-- PROGRAM-ARGS..]`: prints the return value (an entry's Int status too) and exits 0; a built binary exits with the returned Int. `--allow` accepts `io.out io.in env.read fs.read fs.write fs.delete hid.io hid.grab vinput.emit net.http proc.run time.now rand` (repeat the flag for multiple effects). All diagnostics, including static check warnings/errors and `<arg>` parse/type errors, go to stderr; stdout contains only program output and the printed result.
- `serve MOD.FN [PATH..] [--cgi] [--host H] [--port N] [--public] [--allow EFF]..`: serve a named HTTP handler; default loopback listener 127.0.0.1:8080, port 0 chooses a free port; `--cgi` reads one CGI request. Non-loopback binds require `--public` (usage exit 2). See SPEC 8 and DEPLOY-CGI.md.
- `build [--serve] MOD.FN [PATH..] [-o OUT] [--target go|py] [--os linux|darwin] [--arch amd64|arm64] [--no-contracts] [--keep-go DIR]`: ordinary entry has no params and returns Unit or Int exit status; `--serve` instead selects a named `http.Request -> http.Response` handler with no declared `fails` (E-SERVE otherwise), emitting CGI by default with optional built `--listen [--host H] [--port N] [--public]`; default target is `go` (needs `go` on PATH or `$LM_GO`). Target `py` emits a standalone executable Python script (`<fn>.py` by default) with no external compiler requirement; `--os`, `--arch`, `--keep-go` are rejected with `--target py`. Go builds that reach a HID primitive on a macOS target require a macOS host with a C compiler and the macOS SDK. They enable cgo to link the system frameworks. Cross-building such a program from another host exits 3. All other Go builds use `CGO_ENABLED=0`.
- `bench [--tokenizer anthropic] | bench --project PATH [--json]`: without `--project`, writes bench/results/summary.md; tasks in bench/tasks (optional `--tokenizer anthropic` adds a dev-only real-tokenizer S5 via bench/count_tokens.py, needs ANTHROPIC_API_KEY, never falls back). With `--project PATH`, measures S1 and S2 on the project at PATH without overwriting bench/results/, outputting a markdown table plus JSON (or JSON only with `--json`).

## Queries
- `index [PATH..] [--stdlib] [--ext] [--exported] [--modules | --module M]` lists symbols. `--stdlib` adds standard library symbols and `--ext` adds first-party extension symbols, including extensions the project has yet to declare. `--stdlib --modules` lists stdlib and all available extensions with export counts and purposes, marking extensions with `opt-in: (ext STEM) in lm.deps`. `--ext --modules` lists only extensions. `--module M` shows one project, stdlib, extension or declared pinned module with its notes directly below its header when present. Undeclared extensions carry the opt-in marker. Lines from pinned modules, including notes, have an `ext ` prefix and are untrusted data. `--modules` and `--module` are mutually exclusive and reject PATH arguments. An unavailable M exits 3 and lists available names on stderr.
- `slice SYM [--bodies --depth N --budget T]`: root + callee signatures + type closure. Every line of an external module block is prefixed with `ext `, matching index provenance. These display annotations mean marked slices are not parseable LM text.
- `callers SYM [PATH..]`, `deps SYM [--depth N]`, `hash SYM`
- `explain SYM`: human-readable summary.

## Editing
- `edit OP ARGS.. [--in PATH].. [--dry-run] [--force]` (`--force` lets `remove-decl`/`remove-fn` remove a function or const that still has references, or `rename` rewrite scenarios mentioning a renamed variant). Ops: replace-body replace-decl add-decl remove-decl remove-fn rename set-purpose set-sig add-use remove-use add-export add-eff add-fails add-example replace-ref apply (table in docs/SPEC.md section 15).

- `edit add-ext STEM [--dry-run]` adds a first-party extension to the current project's `lm.deps`. The E-EXT-UNDECLARED fix can also be passed to `edit apply`. Dry runs show the manifest diff.

## Acceptance
- `accept [--review|--guard|--bless] [--approve DIGEST.. --by "TEXT"] [--retire NAME.. --by "TEXT"] [--dir D] [--lock F]`: scenarios in tests/accept (`--dir`), lock file accept.lock (`--lock`), file format in docs/TESTING.md "Acceptance scenarios". `--approve` records owner approval (non-interactive); `--retire` drops the lock lines of renamed or deleted scenarios on the owner's word (refuses names still present or not locked); `--bless` is human-interactive.

## Exit codes
0 ok / 1 errors or LM failure / 2 toolchain bug / 3 usage / 70 runtime fault (E-OVERFLOW, E-RECURSION-LIMIT, contract violation).

## Public export
- `scripts/export-public.sh DEST [--scan-only]`: export a clean HEAD without private environment details, or scan the current tracked public files; never commits or pushes.
