# PRD — LM (working name: LMLang)

Status: draft v0.1 · Date: 2026-10-15 · Owner: the project owner · Author/primary user: Claude (AI agent)

## 1. Problem

Mainstream languages are shaped by human limits: typing effort, short working memory for syntax, taste. An AI agent has different limits:

| Agent limit | Consequence in today's languages |
|---|---|
| Finite context window; recall degrades with distance | Understanding one function needs several files; I load too much or guess |
| Fluent confabulation | I write APIs/names that "could exist"; failure shows up late (runtime) |
| Output tokens are slow, costly, irreversible | Boilerplate and whole-file rewrites for small edits |
| Weak at long exact bookkeeping (mutation tracking, counting) | Bugs from hidden state and action at a distance |
| Strong at pattern matching and at feedback loops | Under-used: errors are prose, tests live elsewhere |

## 2. Thesis (falsifiable)

A language and toolchain designed around those limits lets an agent (a) work from small dependency-closed slices instead of the whole codebase, (b) have invented names/effects rejected before runtime, and (c) change code with small edit operations instead of regenerated files — with fewer total tokens and fewer defects than the same work in Python.

The thesis is tested by the benchmark in section 7. If it fails, the fallback is a strict subset + toolchain on top of an existing language (see ADR-011), reusing the tooling built here.

## 3. Users

- **Primary: AI agents** (Claude and others) writing, reading, and modifying LM programs. Every design choice is judged by agent cost/accuracy.
- **Secondary: the human owner** — does not read the code in practice. The human is the *oracle for intent*: confirms behavior is what they meant, via acceptance scenarios and plain-language `explain` output. Human-readability is kept sufficient for audit, never optimized at the agent's expense.

## 4. Goals

G1 Locality: any function is understandable from its own text + the *signatures* of what it references.
G2 Exact resolution: every name has exactly one referent, found by explicit declaration; unknown name = compile error.
G3 Declared contracts: purpose, effects, failures, pre/postconditions, examples are syntax, not comments.
G4 Cheap context: toolchain answers index/slice/callers/deps queries; slices are guaranteed sufficient (by G1).
G5 Cheap edits: change code by AST operations, output proportional to the change.
G6 Machine-first feedback: diagnostics are structured JSON with stable codes, node paths, suggested fixes.
G7 Human-verifiable behavior: human-approved acceptance scenarios are the binding spec; agent cannot silently alter them.
G8 One canonical way: one syntax per concept, one canonical text form (printer = formatter).

## 5. Non-goals (v0)

- Performance of generated code; interop/FFI; concurrency; macros; a package registry. Floats were excluded for v0 and landed in M9 as finite-only binary64 `Float` (ADR-039).
- Human typing comfort, syntactic sugar, IDE niceties.
- Beating existing languages in general. The target is the agent workflow only.

## 6. Requirements

Language (details in docs/SPEC.md)
- R-L1 S-expression syntax, no comments (prose lives in `purpose`/`note` nodes), lowercase-kebab values, Capitalized types/variants/errors.
- R-L2 Immutable values; no mutation, no globals, no inheritance, no overloading, no implicit conversion.
- R-L3 Cross-module references are qualified (`list.map`) and require `(use list)`; prelude is closed and listed.
- R-L4 Functions declare `purpose`, `sig`, optional `eff`, `fails`, `requires`, `ensures`, `example`; absent `eff` = pure, absent `fails` = total.
- R-L5 Sum/record types, exhaustive `match`, Opt built in.
- R-L6 Exported functions require >= 1 example.

Toolchain (details in docs/ARCHITECTURE.md)
- R-T1 `lm check`: parse, resolve, type, effect and failure checking; JSON diagnostics; non-zero exit on error.
- R-T2 `lm test`: run examples, requires/ensures.
- R-T3 `lm fmt`: canonical form; `check` warns when a file is non-canonical.
- R-T4 `lm index | slice | callers | deps | hash`: context-cheap queries.
- R-T5 `lm edit`: operations listed in docs/SPEC.md section 15 (replace-body, add-decl, remove-fn, rename, set-sig, set-purpose, add-use/eff/fails/example/export, replace-ref, apply a diagnostic fix); always re-check and print diagnostics.
- R-T6 `lm run`: interpreter with capability gating (`--allow io.out`).
- R-T7 `lm explain`: plain-language rendering of a function for the human.
- R-T8 `lm accept`: run acceptance scenarios, human-readable report, approval lock guard.
- R-T9 `lm bench`: measure the success metrics.

Quality
- R-Q1 Zero third-party dependencies; Python >= 3.10; runs on macOS and Linux.
- R-Q2 Deterministic output (sorted, stable ordering) so diffs and hashes are stable.
- R-Q3 Every diagnostic code documented in SPEC with a test that triggers it.

## 7. Success metrics (decision gate at milestone M6; results in bench/results/summary.md and ADR-024/025)

| ID | Metric | Target |
|---|---|---|
| S1 | Slice size vs whole project text, projects >= 20 functions | <= 25% (median) |
| S2 | Edit-op output size vs regenerating the changed file | <= 30% (median) |
| S3 | Injected "plausible but nonexistent" names/effects caught by `check` before run | >= 90% |
| S4 | Benchmark tasks reaching green `check`+`test` within 2 agent iterations | >= 80% |
| S5 | LM source tokens vs equivalent Python (incl. contracts/examples) | <= 1.3x |
| S6 | Human acceptance: approved scenarios pass, and zero approved scenarios modified by the agent | 100% |

Token counts use a documented heuristic (ADR-012); the Anthropic tokenizer (`lm bench --tokenizer anthropic`, ADR-052) is the reference for S5. Ratios, not absolutes, matter.

## 8. Risks

| Risk | Mitigation |
|---|---|
| I am trained on existing languages and will be worse at LM at first | Syntax is plain S-expressions; one-page cheat sheet in AGENTS.md; S4 measures it; fallback ADR-011 |
| Ceremony (purpose/sig/example) cancels token savings | S5 measures; prune clauses that don't catch errors |
| Humans cannot review code | Human oracle model (G7); `explain`; approval lock |
| Over-engineering before evidence | Milestones are gated; M6 benchmark decides continuation |
| Canonical-form churn breaks hashes/diffs | Printer rules frozen in SPEC; round-trip property tests |

## 9. Decisions already taken (no open questions for the owner)

Name `LM` / `.lm`; reference implementation in Python stdlib-only; S-expressions; text files as storage with canonical printing (content-addressed store deferred); qualified-only references; closed prelude; finite-only `Float` since M9 (ADR-039). See docs/decisions/ for rationale and revisit triggers.

## 10. Milestones

M0 reader/printer through M12 are done (history in docs/archive/milestones-M0-M12.md); open work is in docs/ROADMAP.md. Gate outcome: S1-S4 and S6 met on the benchmark (with the caveats in ADR-024), S5 open with an owner waiver (ADR-025): 1.34x at the gate, now 1.302x with the Anthropic tokenizer (1.28x heuristic).
