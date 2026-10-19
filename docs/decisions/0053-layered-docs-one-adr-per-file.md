# ADR-053 Layered docs, one ADR per file; supersedes ADR-013 (2026-10-17)

Context: AGENTS.md had grown to ~12 KB (cheat sheet, full command reference, fixture layout, file-by-file notes, machine notes) and docs/DECISIONS.md was a single 78 KB append-only log, so every agent startup and every ADR lookup paid for far more context than it used. The owner's global documentation standard (three layers) applies to all projects.

Decision: three layers. (1) AGENTS.md, always loaded, hard limit ~60 lines / ~4 KB, exactly four sections: What and why, Current step, Rules, Index; CLAUDE.md and GEMINI.md only point to it. (2) Reference docs in docs/, read on demand by section: SPEC, CHEATSHEET (moved out of AGENTS.md), COMMANDS (moved out of AGENTS.md), ARCHITECTURE, TESTING, ROADMAP (open backlog only), EVIDENCE, EXPERIMENTS, ENVIRONMENT (machine notes moved out of AGENTS.md). (3) History: docs/decisions/NNNN-slug.md (the old log split losslessly, one ADR per file, index in docs/decisions/README.md), git log, and docs/archive/ (finished milestones table, AGY's 2026-10-16 review).

Why: startup cost drops by about two thirds, and an ADR lookup reads one small file. No content was deleted; detail moved down a layer.

Revisit: if AGENTS.md exceeds ~4 KB again, or agents repeatedly need a layer-2 file at startup (then promote one line to the index, not the content).
