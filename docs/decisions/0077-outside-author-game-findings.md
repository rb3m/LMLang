# ADR-077 Outside-author findings from lm-arty: diagnostics, `str.cat`, three declines (2026-10-20, agent consensus)

Context: a fresh agy session wrote an artillery game in LM from the onboarding alone (`~/Code/lm-arty`, v0.11.3) and filed five friction points in its `LMLANG_ASSESSMENT.md`. Constraint: don't break the current language, and don't override earlier ADRs.

Decision:
1. Exporting a variant (`(export Hit)`) keeps E-NAME-UNRESOLVED. The message now names the parent sum type (`expected` = parent), and a fix replaces the atom with the parent, or removes it when the parent is already exported. Export semantics are unchanged (exporting a sum type exports its variants).
2. Declined: a tolerance clause for Float examples (`(within 0.1)`). Float results are bit-identical across the interpreter, Go and Python by contract (ADR-039/057; SPEC 8), so the reported mismatch came from a typed approximation, not platform drift. A tolerance would weaken examples and add a rule. Instead, the guide says to copy `found` from E-EXAMPLE-FAILED or compare a `float.fixed` string.
3. Added `str.cat (parts (List Str)) -> Str` = `(str.join parts "")`, written in LM with no new prim. Rejected: a `str.format`/`str.fill` template, which is variadic (would need a special form) or a mini-language inside strings that the checker can't see; doing nothing. No implicit conversion (ADR-007).
4. A parameter or local named `result` keeps E-DUP-NAME, and `result` stays reserved. No `$result` and no new code: ADR-047 says rename on a collision, and consumers already match on the code. The message now names the actual collision (reserved word, module fn, module const, binding in scope), and for `result` it explains the `ensures` binding and suggests `res`.
5. Declined: preserving source order in `lm fmt`. Sorting by name is the canonical form (SPEC 2 rule 5), and edits are AST operations (ADR-022). The guide and the `lm new` onboarding now say that fmt reorders definitions, so use `lm edit` or re-read the file before making text edits.

Who agreed: Claude proposed all five; agy and Codex (gpt-6.1-sol) agreed with each. Codex added that the variant-export fix must not create a duplicate export when the parent is already listed, and that the `res` suggestion should only be made if that name is free.
