# ADR-044 Outside-author experiment: findings and fixes (2026-10-16)

agy wrote a 6-module, ~19k-token ledger application in LM from the docs alone (EVIDENCE.md; branch m9-app keeps the program and its EXPERIENCE.md log). Its top problems, and what was done:
1. A type alias used in a record field was rejected when the alias sorts after the record (`BudgetRule` before `Cents`), blamed on the alias at line 1. Same declaration-order family as ADR-022 and ADR-038: the resolver's pre-pass now also records alias bodies before any field is resolved (fixture type-forward-ref extended; alias cycles still E-CYCLE).
2. An extra `)` that closes the module early reported "found N forms" at line 1 (or "unexpected `)`" at the end of the file). The reader now points at the `)` that closed the top-level form and names where the next form starts (fixture tests/spec/diag/parse-early-close).
3. Deep `match` pyramids over `Opt` (7 levels when parsing one CSV row) cause most paren errors and cost tokens: candidate for M10 (Opt combinators or a short-circuit binding form; decided by consensus there).
4. Missing stdlib: `list.sort-by`, `list.take`/`drop`, string padding (M10 stdlib batch with backlog item 4).
5. The `.accept` format lives in docs/TESTING.md, which AGENTS.md did not point to, and the scoping of scenario constants was undocumented: AGENTS.md now points there and TESTING.md states the rule.
Not merged: the ledger program itself (it would add ~19k tokens to every default `index`/`slice` scope and its scenarios are unapproved); it stays on branch m9-app as a benchmark candidate for backlog item 9.
