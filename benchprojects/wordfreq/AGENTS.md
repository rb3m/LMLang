# AGENTS.md: wordfreq (an LM project)
LM is a programming language for AI agents: s-expression syntax, every function declares purpose, signature, effects, failures and examples, and the toolchain answers structured queries. Run `lm guide` once before writing code (syntax, workflow, stdlib); `lm help CMD` for any command.
## Loop
1. Orient: `lm index`, `lm index --stdlib`, `lm slice wordfreq.FN`.
2. Change code with `lm edit` ops (`lm help edit`), not by rewriting files.
3. `lm check` then `lm test` until both are clean; fix diagnostics by their code and path.
4. `lm run wordfreq.main --allow io.in --allow io.out -- ARGS` to try it; `lm build wordfreq.main` for a native binary (needs Go) or `--target py`.
## Scenarios (the human's spec)
- tests/accept/*.accept hold behavior the human approves. Add new ones with (status proposed).
- Walk the human through each with `lm accept --review`. Only after their explicit yes: `lm accept --approve DIGEST --by "<their words>"` (`--retire NAME --by ..` for renamed or deleted ones).
- Never approve on your own judgment, never edit accept.lock, never run `--bless`.
## Done
`lm check`, `lm test` and `lm accept --guard` are all green.
