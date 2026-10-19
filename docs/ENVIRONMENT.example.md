# Environment: machines, agents and remotes

Read when building with Go, running another agent, pushing, or testing on a different machine. Private checkouts may keep local details in `docs/ENVIRONMENT.md`; this public example describes the supported setup.

## Hosts and toolchains

- Supported hosts: Linux and macOS. Python >= 3.10 is required; the reference implementation uses only the standard library.
- `bin/lm` uses `python3` by default. Set `LM_PYTHON` to the executable for another supported Python interpreter.
- Go >= 1.21 is required for `lm build --target go` (the default target). `lm build --target py` emits a standalone Python script and does not need Go.
- Go discovery order: if `LM_GO` is set, use that file (an invalid override does not fall back); otherwise search `PATH`, then `~/.local/go/bin/go`, `/usr/local/go/bin/go`, `/opt/homebrew/bin/go`, `/usr/local/bin/go`, in that order. Set `LM_GO` to the Go executable, rather than its directory.
- Go-dependent tests print a visible skip when Go is unavailable. Put Go on `PATH` when running the complete suite.
- Cross-build native binaries with `--os linux|darwin` and `--arch amd64|arm64`.

## Git

Configure remotes for your checkout. Commit after each coherent change, push only when asked, and never rewrite history. The public export workflow is documented in `docs/COMMANDS.md`.

## Other agents

Install and authenticate the agent CLIs you use separately, then put them on `PATH`. For example, invoke Codex with `codex exec "TASK" < /dev/null` or agy with `agy -p "TASK"`, using the permissions appropriate to your environment. Follow AGENTS.md for delegation and design consensus. If an agent's sandbox cannot commit, have the coordinating agent or human commit its reviewed changes.
