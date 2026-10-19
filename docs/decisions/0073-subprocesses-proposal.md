# ADR-073 Backlog 25: subprocesses (2026-10-19, agent consensus; owner approved)

Status: accepted (2026-10-19). Design agreed by agy, Codex and Claude in two rounds; the owner approved it, including the known limits below, and queued it after backlog 19.

Decision (all agreed):
1. One effect `proc.run` in the closed set. Any child can read, delete, open the network or start a shell, so narrower effects would promise protections they cannot enforce. `lm run` needs `--allow proc.run`; built binaries run children with the launching user's authority. Effects declare capability use; they do not sandbox the child.
2. API (module `proc`): `(run argv stdin cwd env) -> Result`. argv is a nonempty `(List Str)` executed directly: no shell, expansion or interpreter fallback; argv[0] must be an absolute path. stdin is Str (empty = immediate EOF). cwd is `(Opt Str)`: None is the program's cwd, Some an existing directory. env is `(List (Pair Str Str))` and is exactly the child's environment: nothing is inherited, not even PATH or TMPDIR; a program that wants them reads them with `env.lookup` (env.read) and passes them on.
3. `(which name dirs)`, LM-written under fs.read, searches only the directories the program passes (for example from `(env.lookup "PATH")`) and returns an absolute path, so ambient PATH is used only on purpose.
4. Result: `(rec (exit Exit) (stdout Str) (stderr Str))`, sum `Exit = (Exited Int) | (Signaled Int)`. Nonzero exits and signals are ordinary results.
5. Fixed limits: 30 s total, 8 MiB stdin, 8 MiB combined stdout+stderr, 64 KiB combined argv+env (encoded bytes). stdin is written while both outputs are drained (no pipe deadlock). The child gets its own process group; on timeout or limit the group is killed and reaped, and no partial output is returned. No unrelated file descriptors are inherited.
6. Output is strict UTF-8; invalid bytes fail `invalid-utf8` (as HTTP). NUL in any string, empty or invalid env names and duplicate env keys are `invalid-request`.
7. `proc.ProcError (msg Str)` with fixed categories `invalid-request denied unsupported not-found permission spawn io timeout limit invalid-utf8`, never echoing argv, env, input or host messages.
8. POSIX only (macOS, Linux) in v0; elsewhere `unsupported` before spawning. Parity across interpreter, Go (os/exec) and Python (subprocess) with shared real-process fixtures.
9. Effect mocking (ADR-072): examples script exact calls and their results or errors in order; an unmatched or unused entry fails the example; the fake world never spawns. Owner-reviewed scenarios cover success, nonzero exit, signals, env and cwd, encoding, timeout cleanup and overflow.
10. Deferred: pipes, streaming, background processes, PTYs, binary or lossy output, sandbox policies, a command allow-list.

Known limits (the owner should accept these knowingly): no command allow-list in v0 (both agents recommend none: an executable list cannot constrain arguments, interpreters or replaced binaries; if wanted later, a versioned policy embedded at build time and required by `lm run`). Process-group kill cannot catch descendants that leave the group, and child CPU, memory and disk use are not bounded; containing hostile programs needs OS sandboxing outside the stdlib.

Who agreed: round 1, agy and Codex agreed on items 1, 5 (limits and group kill), 4 (exits are results), 7, 9 and 10; they split on PATH lookup (agy yes), inherited minimal env (agy PATH and TMPDIR), lossy UTF-8 (agy) and the result shape. Round 2, both accepted Claude's tie-breaks (absolute argv[0] plus `which`, no inherited env, strict UTF-8, the Exit sum, POSIX only, Opt cwd). agy's Latin-1 concern is the revisit trigger for lossy output.
