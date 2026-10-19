# ADR-058 Module-level constants and variant rename (backlog 6; 2026-10-18, agent consensus)

Context: a constant today is a zero-parameter function (`(fn max-burn (purpose ..) (sig -> Float) (example () => 12.0) (body 12.0))`, called `(max-burn)`): four clauses and a call for one value, and `lm index` cannot show the value. Backlog 6 also asks for renaming sum-type variants in `lm edit` (v0 refuses).

Decisions:
1. Form: `(const moon-gravity (purpose "Lunar surface gravity, m/s^2.") (type Float) (value 1.62))`. `purpose` and `type` are required (no inference, like `sig`); no examples; exported through `(export ..)`; constants share the value namespace with functions (a collision is the existing duplicate error).
2. Value: any pure expression with no effects, no declared fails and no type variables in its type. It may reference constants and call pure functions. A cycle in the static reference graph (const -> const, or const -> fn -> const) is E-CYCLE.
3. Evaluation: `lm check` evaluates every constant on every run (nothing cached across runs), under a step budget so a runaway expression cannot stall the check; a fault, a failure or an exhausted budget is reported at the constant's node path. The interpreter uses the value computed at load. `lm index`/`slice` show `const NAME Type = VALUE`. Native builds compile the expression and initialize the values at startup in dependency order (the generated Go is one package); differential tests require bit-identical values.
4. Reference: a bare name, not called (`moon-gravity` in its own module, `roadster-levels.moon-gravity` elsewhere), in bodies, contracts, examples, other constants and, qualified per ADR-056, `lm run` arguments and scenario values.
5. Edit ops: `add-decl`, `replace-decl` and `rename` accept `const`; new `remove-decl` removes a fn or const (refusing while references exist unless `--force`); `remove-fn` stays as an alias.
6. Variant rename: `lm edit rename mod.Variant NEW` (only this spelling; variants are module-scoped) updates the definition, constructors, patterns and qualified uses; rolled back on any new error. If a `.accept` file mentions the variant, rename refuses unless `--force`; with `--force` it rewrites the scenario text and returns each touched scenario to `proposed` for owner re-approval (ADR-055).
7. Out of scope: `float.pi`/`e` stay zero-parameter functions (ADR-057; a migration is its own decision); record field renames.

Who agreed: Claude proposed 1-7; agy agreed on 1-4 and 7, amended 5 (`remove-decl` with the alias) and 6 (only `mod.Variant`), and added the scenario rewrite under `--force`, the check-time step budget, no stale cached values and init ordering, all adopted. Codex was out of usage; the owner authorized proceeding on Claude + agy agreement.
