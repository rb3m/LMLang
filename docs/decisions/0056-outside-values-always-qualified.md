# ADR-056 Outside values are always qualified (backlog 12; 2026-10-17, owner decision after agent disagreement)

Context: `lm run` prints variants and records module-qualified (`(shapes.Circle 6)`), and SPEC promised that a printed value is a valid example constant. But `lm run` arguments and acceptance-scenario values were checked in the target function's own module scope, where its own names must be unqualified (SPEC section 16 name rules, ADR-047), so the output of `lm run shapes.scale` could not be pasted back into `lm run shapes.area` or into a scenario.

Options: (A) in these outside contexts accept both spellings, rewriting `shapes.X` to `X` (agy; Claude's first lean); (B) outside contexts have no own module, so every module-defined name is qualified (Codex); (C) print values relative to the target module (rejected by all: output would depend on which function ran).

Decision (B): `lm run` arguments and scenario `run` arguments, `expect` values and `expect-fail` arguments are an outside scope. Variants, record types in `new` and errors of any module, including the target's own, are written qualified; prelude names stay unqualified. An unqualified own-module name there is E-NAME-UNRESOLVED with a message naming the qualified form. Module source and examples keep the existing rule (own names unqualified). One shared code path checks run arguments and scenario values.

Why: one spelling per context keeps the rule an AI author must learn to "inside a module, own names bare; outside, always qualified", and printed values round-trip everywhere. A would have been the first two-spelling exception to ADR-047.

Who agreed: agy recommended A (no breakage); Codex recommended B (one canonical form; the compatibility cost is bounded). Claude switched to B on Codex's argument. Because the agents disagreed and approved scenarios were affected, the owner decided: B.

Consequence: the three approved scenarios in `tests/accept/shapes.accept` were rewritten with qualified names, returned to `proposed`, and re-approved by the owner on 2026-10-17 through the ADR-055 review ("approved all three ✅"), the first use of `lm accept --approve`.
