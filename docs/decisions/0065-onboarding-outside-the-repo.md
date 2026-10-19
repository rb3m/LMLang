# ADR-065 Backlog 22: onboarding an AI outside the repo (2026-10-19, agent consensus)

Context: every LM program so far (Roadster Lander, the M9 ledger) was written inside this repo with docs/CHEATSHEET.md, SPEC and the ADRs at hand. An agent in someone else's directory had only `lm`, whose usage line was hand-written and stale (no `build --target py`, `accept --approve/--retire`, `bench --project`), `lm help` was "not implemented", and `lm new` scaffolded no instructions.

Options for the guide text: (a) move the cheat sheet into the package as the single source; (b) keep docs/CHEATSHEET.md and copy it into the package with a drift test; (c) read the docs file at runtime (fails outside a checkout).

Decision:
1. Guide: (a). `lm/guide.md` (moved from docs/CHEATSHEET.md) is self-contained: no repo paths, a Workflow section first (index/slice before reading, `lm edit` ops, check -> test, JSON diagnostics with fixes, scenario approval only on the human's explicit yes, never `--bless`), a scenario file format section, and an `io.print`/`io.eprint` line. `lm guide` prints it. AGENTS.md indexes it as `lm guide`.
2. Command registry: `lm/commands.py`, one entry per command (synopsis with every flag, summary, handler as a lazy `module:function` string, so no import cycle). Dispatch, usage, `lm help [CMD]` (also `--help`, `-h`; `help edit` adds the op table) come from it; `--version`/`-V` print `lm 0.0.1`. Unit tests tie it to docs/COMMANDS.md, to each handler's source (every synopsis flag is a string literal there) and to SPEC section 15's op table.
3. `lm new` also writes AGENTS.md (<= 25 lines: what LM is, `lm guide` first, the loop, scenario rules) and CLAUDE.md/GEMINI.md pointers.
4. Proof: a cold-start run (EVIDENCE 2026-10-19), a fresh agent in an empty directory outside the repo, with PATH holding only `lm` and the runtimes, building a word-frequency CLI from a spec fixed in advance. Kept as `benchprojects/wordfreq`.

Found by the run and its setup, fixed here: macOS's system `python3` (3.9) crashed with a TypeError (now an exit-3 message naming the needed version and `LM_PYTHON`); `lm new` printed a traceback on an unwritable directory (now a one-line message, exit 1); `lm run` printing the returned Int and exiting 0 was undocumented (now in `help run` and COMMANDS). Queued as backlog 24, not fixed: `accept --guard` passes while a proposed scenario is malformed; `index --stdlib` (15 KB) is over half of what a new agent reads.

Why: one source cannot drift; generated help cannot omit a flag; the scaffold reaches agents that never see this repo.

Revisit when: LM is installed without a checkout (packaging, backlog 23), or a second cold-start run by a different agent family disagrees.

Who agreed: agy agreed with all four points and added `--version`, the index/slice pointer and the edit-op rule. Codex (gpt-6.1-sol) agreed on 1, and asked for lazy handlers, the parser drift test, stricter scenario wording, runtime prerequisites on the cold-start PATH, edit-op syntax in help and a spec fixed before the run. Claude adopted all of it. Implementation by Codex (gpt-6.1-sol), verified by Claude.
