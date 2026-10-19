# ADR-070 Backlog 16: user-defined generic types (2026-10-19, agent consensus)

Context: every container had to be re-declared per concrete type; the built-in `Pair` (ADR-059) was a workaround. This was the largest language-level gap.

Decision:
1. Declaration: the name becomes a head list with distinct single-letter params: `(type (Tree a) (sum Leaf (Node (left (Tree a)) (value a) (right (Tree a)))))`, records and transparent aliases alike. Each param must be used; no other free variables. Declaration params and signature type variables are separate scopes. `(export Tree)` uses the bare name.
2. Use: `(Tree Int)` / `(mod.Tree Str)` anywhere a type goes. Wrong arity, a bare generic name, or applying a non-generic name is E-TYPE.
3. Construction and patterns infer arguments by unification; every constructor use (including first-class) gets fresh variables; `(new Box (item 1))` is the only record form; `get`, `with` (keeps the instance's arguments) and `match` substitute arguments into field types.
4. Regular recursion only, checked across each strongly connected set of declarations including alias expansion (`lm/generic_cycles.py`); recursive aliases stay E-CYCLE. No higher kinds, no constraint syntax.
5. Existing rules apply at instantiation: the Map key / Set element rule propagates through generic fields and aliases; `=` rejects instantiated types containing `Fn` (cycle-safe); consts are fully instantiated.
6. Runtime erasure: values keep their representation in interpreter, Go and Python targets; printing unchanged. Tooling (printer, hash, slice closure, explain, rename, external values in `lm run` and scenarios) handles generic heads.
7. Opt, Pair, List, Map and Set stay built in; a stdlib `Result` is a separate item if wanted.

Verification: 29 spec fixture pairs, unit tests, `examples/tree.lm`, 724 differential cases identical across the three runtimes; Claude's adversarial probes (arity, bare names, non-regular and mutual recursion, `with`/`new`/`match` substitution, fresh constructor variables, map keys, Fn equality, phantom params) all behaved as specified; an independent agy review found no correctness bugs.

Revisit when: a program needs non-regular recursion, constraints, or a stdlib Result.

Who agreed: agy agreed with all points and added bare-name export, non-recursive aliases and nullary variants in external values. Codex (gpt-6.1-sol) agreed and tightened regularity across mutual cycles and aliases, transitive key propagation, cycle-safe equality, argument-aware unification and fresh constructor instances. Implementation by Codex (gpt-6.1-sol, high effort, for a cross-cutting type-system change); review by agy and Claude.
