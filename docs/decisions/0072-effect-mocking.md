# ADR-072 Backlog 20: effect mocking with hermetic `given` examples (2026-10-19, agent consensus)

Context: examples were rejected on effectful functions, so files, clock, input and random code were covered only by scenarios and runtime cases.

Options: host sandbox (temp dir, real env and clock), capability injection in user code, or a fake world owned by the test runner. The fake world won: deterministic, no host access, no change to how programs are written.

Decision:
1. Syntax on fns that declare effects only: `(example (ARGS) (given CLAUSE..) => RESULT CHECK..)`. `given` is required there (may be empty) and is E-EXAMPLE on a pure fn. Given: `args`, `stdin`, `env`, `file`, `dir`, `now-ms`, `seed`. Checks: `out`, `err`, `file`, `no-file`, `dir`, `no-dir`.
2. A fresh hermetic world per example, shared by nested calls: empty args, stdin, env and filesystem by default; both clocks frozen at `now-ms` (default 0); a fresh PRNG from `seed` (default 0, same stream as `--seed`). The host is never touched. The fake tree has regular files and directories only (no symlinks, permissions or encoding failures) and follows ADR-068 semantics; paths use an exact grammar (no empty, `.` or `..` components, no trailing `/` or NUL); invalid paths fail `fs.IoError` at runtime and are E-EXAMPLE in `given`/checks.
3. Results then every check are compared, also after an expected `(fail ..)`. With `io.out` declared, an absent `out` means stdout must be empty (same for `err`).
4. Check-time E-EXAMPLE: constant contents, arity and types, unknown or duplicate clauses, duplicate env keys, conflicting or parentless paths, contradictory checks, Int64 range, and each clause needing its effect (fs checks need fs.write or fs.delete).
5. Interpreter only; excluded from compiled differential enumeration (runtime cases stay real-effect). R-L6 unchanged.

Verification: Claude ran the full gate and probes: nested calls share the world, dir rename moves the subtree, rename never overwrites, `HOME` is not visible, a write of `HOSTLEAK` left no host file, seeded draws equal `lm run --seed` and the compiled Python target, and all 19 effectful prims route to the fake world (unknown fs ops fail closed).

Who agreed: agy and Codex (gpt-6.1-sol) agreed on the fake-world design with Claude. agy added `dir`/`no-dir` checks, default `now-ms` 0 and the absent-stream-must-be-empty rule; Codex added the path grammar, fresh-world-per-example, the check-time rules and the effect mapping for checks, and kept R-L6 unchanged. agy wanted `given` optional; Codex's required `(given)` was adopted because it marks the example as hermetic. Implemented by Codex (gpt-6.1-sol, high effort; resumed after a usage-limit pause), verified by Claude.
