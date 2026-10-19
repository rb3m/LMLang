# ADR-074 Backlog 17: persistent vector `(Vec a)` (2026-10-19, agent consensus)

Context: lists are immutable linked sequences, so grids, simulations and large tables pay O(n) per indexed read or update.

Options: a mutable array behind an effect (breaks value semantics, `=` and printing), a balanced tree map keyed by Int (heavier and unordered by intent), or a persistent vector. The persistent vector won: values stay immutable and comparable, and updates share structure.

Decision:
1. Built-in persistent immutable `(Vec a)`, any element type: a 32-way trie with a tail in every runtime; no RRB or fast concat in v0.
2. Module `vec`: `empty from-list to-list size at set push pop last fold map repeat tabulate`. `at` -> `(Opt a)`, `set` -> `(Opt (Vec a))`, `pop` -> `(Opt (Vec a))`, `last` -> `(Opt a)`; `fold` steps `(acc elem)` in increasing index; `repeat n x` and `tabulate n f` give empty for n < 0. Indices from 0; out of range is None, never wraparound. Prelude `len` stays List-only.
3. `vec.nth` and `vec.put` fail OutOfRange with exactly `list.nth`'s proof power under ADR-061: `(vec.size NAME)` is a fact term like `(len NAME)`, compared with Int literals only. Relational (variable vs size) reasoning is deferred.
4. Literal `(vecof e..)`, evaluated left to right, prints in index order, so printed values are external constants. `=` is structural, independent of trie shape; not a Map key or Set element; `for` stays List-only and match has no Vec patterns.
5. Complexity contract: at, set, nth, put, push, pop O(log32 n) worst case; construction, conversion, map, fold, printing and `=` O(n) by leaf traversal.

Who agreed: agy and Codex (gpt-6.1-sol) agreed on 1, 4 and the Opt defaults in two rounds. agy contributed `size` (not `len`), `last`, `repeat`, and the failing nth/put; Codex the worst-case (not amortized) bound, `tabulate`, O(n) traversal, transitive equality and the boundary test list. Codex objected that ADR-061 cannot prove variable indices; the narrowed rule 3 (literal indices only) was agreed in a third exchange.

Verification: Claude ran the full gate, a randomized model test (20,000 push, pop, set and at operations at sizes across trie boundaries, with saved old versions unchanged), a push/pop cycle through 33,000 elements, and a 48x48 Game of Life on Vec that gave the same counts in the interpreter, Go and Python targets and in an independent plain-Python version; proof discharge, Map-key rejection, history-independent `=` and printed-value round trips behaved as specified. Implementation by Codex (gpt-6.1-sol, high effort).
