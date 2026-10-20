# AGENTS.md: LMLang (read this first; read other docs only when the index says so)

## What and why
LM is a programming language and toolchain authored and read by AI agents. It features small dependency-closed slices, exact name resolution, declared contracts/effects, edit-by-operation, and structured JSON diagnostics. It tests a falsifiable thesis (PRD.md section 2); the owner judges intent and does not read code.
Pipeline: `.lm` text -> reader -> AST (stable node paths) -> module graph -> resolve -> types -> effects/fails -> interpreter (oracle), or -> IR -> Go -> static native binary (`lm build`). Python reference impl, stdlib only; s-expression syntax.

## Current step
- Backlog 3-6, 8, 9, 13-20, 22-26 done (ADR-058..076). 21 left: a program the owner uses daily (S5 and DreamHost CGI done, docs/EVIDENCE.md). Public v0.11.2, export only.
- Open: S5 real tokenizer 1.302x vs target <= 1.3x (ADR-025), OPEN by 0.002. Never call it passed.

## Rules
1. Orient with `lm index` (`--stdlib` for stdlib), then `lm slice mod.fn` before opening files; read a whole module only when a slice is insufficient (say why). Run `lm callers` before changing signatures.
2. Change code with `lm edit` ops (`rename`, `apply '<fix json>'`), not by rewriting files.
3. Loop edit -> `lm check` -> `lm test` until clean. Done means `lm check`, `lm test`, `lm accept --guard` and `python3 -m unittest discover tests/unit` are green (Go tests skip visibly without `go`).
4. New check/runtime rule or bug fix: write the failing spec fixture first.
5. Scenarios: propose and walk owner through each (ADR-055, docs/TESTING.md). Only on explicit yes run `lm accept --approve DIGEST.. --by "<words>"` (`--retire NAME --by` for renamed/deleted ones). Never approve on own judgment, hand-edit `accept.lock`, or run `--bless`.
6. Python >= 3.10, stdlib only, zero third-party deps, each module < ~400 lines.
7. If code and SPEC disagree, fix both together. Real alternatives require a new ADR in `docs/decisions/`.
8. Design decisions by agent consensus (Claude, agy, Codex; ADR-030). On collision, rename; never add exceptions (ADR-047).
9. Delegate implementation to Codex/agy first; Claude subagents only for the hardest parts.
10. Commit after each coherent change; push only when asked; never rewrite history.
11. Keep this file <= ~60 lines / ~4 KB, exactly four sections. Update "Current step" when it changes; move detail to layer 2 (ADR-053).

## Index
- `PRD.md`: goals, thesis, metrics S1-S6. Read before touching benchmark or thesis.
- `lm guide` (source lm/guide.md): compact LM syntax, workflow, stdlib reminder. Read before writing/reviewing `.lm` code.
- `docs/SPEC.md`: normative language rules (sections 1-16). Search by heading when `lm guide` is insufficient.
- `docs/COMMANDS.md`: every `lm` command, flag and exit code. Read before using unfamiliar commands.
- `docs/ARCHITECTURE.md`: module layout, pipeline, mechanisms, adding prims. Read before changing `lm/`.
- `docs/TESTING.md`: test layers, fixtures, goldens, acceptance format, human routine. Read before adding tests.
- `docs/ROADMAP.md`: open backlog and current milestone. Read when picking or scoping work.
- `docs/EVIDENCE.md`: thesis datapoints. Append when an experiment yields a measurement.
- `docs/EXPERIMENTS.md`: trying LM on real programs; known gaps. Read when writing in `src/`.
- `docs/DEPLOY-CGI.md`: deploying a `--serve` handler as CGI. Read before deploying.
- `docs/ENVIRONMENT.md` (private checkouts; public: `docs/ENVIRONMENT.example.md`): machines, Go paths, remotes, other agents. Read before building, pushing or switching hosts.
- `docs/decisions/`: one ADR per file, indexed in README; read matching ADR before changing behavior it covers.
- `docs/archive/`: finished milestones (M0-M12) and AGY's 2026-10-16 review (history).
- Code: `bin/lm` (wrapper), `lm/` (Python package; `lm/runtime/go/` Go runtime), `stdlib/*.lm`, `src/` (user programs), `games/`, `benchprojects/` (own LM projects; run `../../bin/lm` inside), `examples/`, `tests/{unit,spec,accept,golden}`, `bench/`.
