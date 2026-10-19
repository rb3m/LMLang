# Decisions (ADRs)

One ADR per file, `NNNN-short-slug.md`, numbered in order; never reuse a number. Format: context -> decision -> why -> revisit trigger (and who agreed, for consensus decisions, ADR-030). Do not rewrite an accepted ADR: add a new one and mark the old one superseded. Read the matching ADR before changing the behavior it covers; `grep -l` this folder by topic rather than reading it all.

## Key rationale (one line each)
S-expressions: lowest syntax-error rate, uniform node paths (ADR-003). Qualified-only names + closed prelude: unknown names are provably errors, killing invented APIs (ADR-005). Declared eff/fails: signatures are complete contracts, so slices need only signatures (ADR-006, ADR-021). Text storage + canonical printer: stable diffs/hashes now, content-addressed store later (ADR-004). Python reference impl: fast iteration, zero deps (ADR-002). Thesis gate with fallback (ADR-011; S5 still open, ADR-025): expand the language only for observed need, record evidence in docs/EVIDENCE.md.

Moved files cited by older ADRs: `AGYS_OPINION.md` is now `docs/archive/2026-10-16-agy-review.md`; `docs/DECISIONS.md` became this folder (ADR-053).

## Index
- [ADR-001](0001-name-and-extension.md) Name and extension
- [ADR-002](0002-reference-implementation-python-stdlib-only.md) Reference implementation: Python, stdlib only
- [ADR-003](0003-s-expression-surface-syntax.md) S-expression surface syntax
- [ADR-004](0004-text-is-storage-ast-is-semantics-no.md) Text is storage, AST is semantics, no comments
- [ADR-005](0005-qualified-only-cross-module-names-closed-prelude.md) Qualified-only cross-module names, closed prelude
- [ADR-006](0006-declared-effects-and-failures-absent-means-pure.md) Declared effects and failures; absent means pure and total
- [ADR-007](0007-deliberate-omissions-in-v0.md) Deliberate omissions in v0
- [ADR-008](0008-structured-diagnostics.md) Structured diagnostics
- [ADR-009](0009-contracts-and-examples-are-syntax.md) Contracts and examples are syntax
- [ADR-010](0010-human-is-the-oracle-for-intent.md) Human is the oracle for intent
- [ADR-011](0011-thesis-gate-and-fallback.md) Thesis gate and fallback
- [ADR-012](0012-token-estimation-heuristic.md) Token estimation heuristic
- [ADR-013](0013-doc-layout.md) Doc layout
- [ADR-014](0014-m0-shape-expressions-stay-s-expr-nodes.md) M0 shape: expressions stay s-expr nodes
- [ADR-015](0015-function-values-are-pure-and-total.md) Function values are pure and total (M1)
- [ADR-016](0016-no-shadowing-of-any-kind.md) No shadowing of any kind (M1)
- [ADR-017](0017-prim-for-stdlib-primitives.md) `(prim "name")` for stdlib primitives (M1)
- [ADR-018](0018-effects-fails-checked-during-inference-not-as.md) Effects/fails checked during inference, not as a separate pass (M1)
- [ADR-019](0019-examples-are-the-semantics-test-suite-run.md) Examples are the semantics test suite; run args are LM expressions (M2)
- [ADR-020](0020-no-tail-calls-host-stack-recursion-limit.md) No tail calls, host-stack recursion limit (M2)
- [ADR-021](0021-slice-root-in-full-signatures-type-closure.md) Slice = root in full + signatures + type closure (M3)
- [ADR-022](0022-edits-are-ast-operations-addressed-by-node.md) Edits are AST operations addressed by node paths; rename uses the reference graph (M4)
- [ADR-023](0023-acceptance-oracle-hash-locked-scenarios-status-excluded.md) Acceptance oracle: hash-locked scenarios, status excluded from the digest (M5)
- [ADR-024](0024-m6-gate-decision-adjust-then-re-gate.md) M6 gate decision: ADJUST, then re-gate (2026-10-15)
- [ADR-025](0025-m7-result-and-owner-waiver-of-the.md) M7 result and owner waiver of the S5 trigger (2026-10-15)
- [ADR-026](0026-native-builds-via-a-go-backend-int.md) Native builds via a Go backend; Int becomes 64-bit with checked overflow (proposed 2026-10-16, M8)
- [ADR-027](0027-adr-026-accepted-server-target-facts.md) ADR-026 accepted; server target facts (2026-10-16)
- [ADR-028](0028-slice-signature-blocks-include-requires-and-ensures.md) Slice signature blocks include `requires` and `ensures` (2026-10-16)
- [ADR-029](0029-overflow-is-an-unchecked-runtime-fault-not.md) `Overflow` is an unchecked runtime fault, not a prelude error (proposed 2026-10-16, amends ADR-026)
- [ADR-030](0030-adr-029-accepted-by-agent-consensus-with.md) ADR-029 accepted by agent consensus, with amendments (2026-10-16)
- [ADR-031](0031-m8-shared-interfaces-entry-points-program-arguments.md) M8 shared interfaces: entry points, program arguments, exit codes, effects in binaries (2026-10-16)
- [ADR-032](0032-m8-implemented-64-bit-int-and-e.md) M8(b) implemented: 64-bit Int and E-OVERFLOW in the interpreter (2026-10-16)
- [ADR-033](0033-sequencing-form-and-list-patterns-in-match.md) Sequencing form `(do ...)` and list patterns in `match` (2026-10-16)
- [ADR-034](0034-m8-utf-8-i-o-and-string.md) M8(a) UTF-8 I/O and string parsing details (2026-10-16)
- [ADR-035](0035-go-backend-v1-ir-shape-dynamic-values.md) Go backend v1: IR shape, dynamic values, failures as panics, bounded recursion (2026-10-16, M8(c))
- [ADR-036](0036-lm-build-interface-details-stdout-buffering-refines.md) `lm build` interface details; stdout buffering refines ADR-031 item 6 (2026-10-16, M8(c)/(d))
- [ADR-037](0037-review-fixes-after-the-m8-merge-evaluation.md) Review fixes after the M8 merge: evaluation order, no function equality, subject-first stdlib (2026-10-16)
- [ADR-038](0038-m8-on-linux-colsum-and-a-resolver.md) M8(e) on Linux: `colsum`, and a resolver pass-order fix (2026-10-16)
- [ADR-039](0039-floating-point-finite-only-binary64-float.md) Floating point: finite-only binary64 `Float` (2026-10-16, agent consensus)
- [ADR-040](0040-tooling-diagnostics-locate-missing-closes.md) Tooling diagnostics locate missing closes (2026-10-16)
- [ADR-041](0041-golden-queries-use-a-fixed-project.md) Golden queries use a fixed project (2026-10-16)
- [ADR-042](0042-cli-command-families-split-without-interface-changes.md) CLI command families split without interface changes (2026-10-16)
- [ADR-043](0043-float-implemented-choices-adr-039-left-open.md) Float implemented (M9): choices ADR-039 left open (2026-10-16)
- [ADR-044](0044-outside-author-experiment-findings-and-fixes.md) Outside-author experiment: findings and fixes (2026-10-16)
- [ADR-045](0045-m10-let-short-circuit-binding-and-a.md) M10: `let?` short-circuit binding and a stdlib batch (2026-10-16, agent consensus)
- [ADR-046](0046-m10-implemented-choices-adr-045-left-open.md) M10 implemented: choices ADR-045 left open (2026-10-17)
- [ADR-047](0047-naming-rule-on-a-collision-rename-no.md) Naming rule: on a collision, rename; no exceptions (2026-10-17, owner guidance)
- [ADR-048](0048-the-lm-command-and-lm-new.md) The `lm` command and `lm new` (2026-10-17)
- [ADR-049](0049-m11-built-in-map-and-set.md) M11: built-in `Map` and `Set` (2026-10-17, agent consensus)
- [ADR-050](0050-m11-implemented-choices-adr-049-left-open.md) M11 implemented: choices ADR-049 left open (2026-10-17)
- [ADR-051](0051-m12-tail-calls-clock-random-json-real.md) M12: tail calls, clock/random, json, real-tokenizer S5, gobackend split (2026-10-17, agent consensus)
- [ADR-052](0052-m12-implemented-choices-adr-051-left-open.md) M12 implemented: choices ADR-051 left open (2026-10-17)
- [ADR-053](0053-layered-docs-one-adr-per-file.md) Layered docs, one ADR per file; supersedes ADR-013 (2026-10-17)
- [ADR-054](0054-roadster-lander-validation-game.md) Roadster Lander: backlog 11 reskinned as a flying-car parking game (2026-10-17, agent consensus)
- [ADR-055](0055-ai-records-owner-approval-of-scenarios.md) The AI records the owner's approval of scenarios; amends ADR-010/023 (2026-10-17, owner decision)
- [ADR-056](0056-outside-values-always-qualified.md) Outside values (`lm run` args, scenario values) are always qualified; backlog 12 (2026-10-17, owner decision)
- [ADR-057](0057-float-math-in-float-module.md) Float math lives in `float`, faults on bad domains, one pinned algorithm per function; backlog 13 design (2026-10-17, agent consensus)
- [ADR-058](0058-module-constants-and-variant-rename.md) Module-level constants (`const`) and variant rename in `lm edit`; backlog 6 (2026-10-18, agent consensus)
- [ADR-059](0059-pairs-and-list-head-tail.md) Built-in `Pair`, `list.head/tail/last`, `zip`, `map.to-list/from-list`; backlog 4 (2026-10-18, agent consensus)
- [ADR-060](0060-for-effectful-iteration.md) `(for (x xs) body)`: per-element iteration with effects; backlog 5 part (2026-10-18, agent consensus)
- [ADR-061](0061-optional-exports-proven-safe-ops-lambda-inference.md) Optional exports, proven-safe division/indexing, inferred lambda types; S5 levers (2026-10-18, agent consensus)
- [ADR-062](0062-python-build-target.md) `lm build --target py`: self-contained Python backend over the IR; backlog 8 (2026-10-18, agent consensus)
- [ADR-063](0063-unicode-casing-codes-escapes.md) Pinned Unicode simple casing, `str.to-codes/from-codes`, ` {..}` escapes, pinned trim whitespace; backlog 3 (2026-10-18, agent consensus)
- [ADR-064](0064-backlog-9-measure-existing-outside-author-projects.md) Backlog 9: measure the existing outside-author projects (M9 ledger, Roadster Lander) (2026-10-18, agent consensus)
- [ADR-065](0065-onboarding-outside-the-repo.md) Backlog 22: `lm guide`, command registry and `lm help`, `lm new` AGENTS.md, cold start outside the repo (2026-10-19, agent consensus)
- [ADR-066](0066-public-export-from-private-repo.md) Public release: Apache-2.0, private history kept, scanned export script builds the public tree (2026-10-19, owner decisions + agent consensus)
- [ADR-067](0067-scenario-validity-in-the-gate.md) Backlog 24: invalid scenarios fail check (E-SCENARIO) and guard; `index --stdlib --modules/--module` (2026-10-19, agent consensus)
- [ADR-068](0068-system-access-env-and-fs.md) Backlog 14: `env.lookup`, fs append/entries/is-dir/make-dir/remove/rename, effects env.read and fs.delete (2026-10-19, agent consensus)
- [ADR-069](0069-http-client-proposal.md) Backlog 15: HTTP client design; PROPOSED, owner decisions R1-R5 pending (2026-10-19)
- [ADR-070](0070-user-defined-generic-types.md) Backlog 16: user-defined generic types `(type (Tree a) ..)`, regular recursion, erased at runtime (2026-10-19, agent consensus)
- [ADR-071](0071-float-fixed-and-dates.md) Backlog 18: `float.fixed` (exact half-even) and the pure `date` module (2026-10-19, agent consensus)
- [ADR-072](0072-effect-mocking.md) Backlog 20: effect mocking, hermetic `(given ..)` examples on effectful fns, interpreter only (2026-10-19, agent consensus)
