# ADR-060 `(for (x xs) body)`: per-element iteration with effects (backlog 5 part; 2026-10-18, agent consensus)

Context: function values must be pure and total, so "print each name" needs a recursive helper (`(match names ((list) unit) ((cons n rest) (do (io.print (greeting n)) (announce rest))))`), the main excess in bench task 13-greet (1.76x Python). Owner rule (2026-10-18): LM is read and written only by AI; fewer tokens beat human readability.

Decision: special form `(for (x xs) body)`.
1. `xs` is a `(List a)` evaluated exactly once; `x` is bound to each element in order, fresh per iteration (closures keep that iteration's value), subject to the no-shadowing rule. `body` must be `Unit`; the form is `Unit`.
2. Effects and declared fails of `xs` and `body` count as the enclosing function's, checked exactly like `do`; no effectful lambdas or effect polymorphism. A failure escaping `body` stops the iteration immediately and propagates (an enclosing `try` handles it normally).
3. `for` is non-strict (body evaluated per element); nothing inside it is a tail position. The interpreter runs it in bounded stack space; native builds compile it to a loop.
4. Diagnostics: a body with no effect and no possible failure is a warning (its result is discarded); `break`, `continue` and `return` are not LM names, and using one inside `for` gets a message saying LM has no early exit (use a recursive function or `list.fold`).
5. Lists only; Maps via `map.to-list` and the `pair` pattern. No accumulator form (tail-recursive helpers already run as loops, ADR-051).

Who agreed: Claude proposed 1-3 and 5; Codex (gpt-6.1-sol) agreed and added evaluate-once, stop-on-failure, fresh bindings and the SPEC 11 updates; agy agreed with all of it and added item 4. Unanimous.
