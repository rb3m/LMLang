# ADR-067 Backlog 24: scenario validity is part of the gate; compact stdlib index (2026-10-19, agent consensus)

Context: in the ADR-065 cold start, an agent wrote `(allow io.out fs.read)`. `lm check`, `lm test` and `lm accept --guard` all stayed green; only `lm accept --review` called it invalid, so the agent believed it was done. `lm index --stdlib` (about 15 KB) was over half of what the agent read.

Decision:
1. `lm accept --guard` fails (`INVALID NAME: problem`) on any scenario, proposed or approved, with a shape problem, without executing anything.
2. Static scenario validation (`lm/accept_validate.py`) is shared by `lm check` and `lm accept`; `execute` validates first. With default scope, `lm check` reports each problem in tests/accept as E-SCENARIO (file and line of the scenario, path `scenario:NAME`): shape (duplicate status/why, allow operands, expectation arity, `expect-out` string), target exists and is exported, args, `expect` and `expect-fail` type-check, allows are known effects and cover every declared effect (full missing set). Nothing is evaluated. No `fix` yet: `lm edit apply` cannot edit .accept files, so the msg carries the repair.
3. `(allow EFF)` stays one effect per clause (G8); the diagnostic and the guide teach `(allow io.out) (allow fs.read)`.
4. A scenario must allow every effect its target declares (SPEC section 13); now stated in `lm guide`.
5. `lm index --stdlib --modules` (one line per module, 824 bytes) and `--stdlib --module M`; bare `--stdlib` unchanged. The guide and `lm new` AGENTS.md start from `--modules`.

Revisit when: `lm edit` learns to edit .accept files (then add fixes), or a second cold start shows another way to slip past the gate.

Who agreed: agy agreed with all four parts. Codex (gpt-6.1-sol) agreed and widened validation (arity, `expect-out` shape, duplicate clauses, allow operands, `expect-fail` types), asked for fixes only where `lm edit apply` can apply them, and for clear unknown-module and flag-conflict errors. Implementation by Codex (gpt-6.1-sol); Claude removed a per-code exception that dropped `fix` from E-SCENARIO JSON (every diagnostic keeps the same shape, ADR-047) and reused prelude.EFFECTS.
