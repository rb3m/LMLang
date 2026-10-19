# ADR-059 Built-in Pair, list.head/tail/last, zip and map lists (backlog 4; 2026-10-18, agent consensus)

Context: backlog 4 asks for tuples or pairs and `list.head/tail`. LM has no tuples, and user `type` declarations take no type parameters, so nobody can define a generic pair; ADR-045 declined `zip` because `list.map2` "builds pairs" into user records. Lists already have `cons` patterns and `list.at -> (Opt a)`.

Decisions:
1. `list.head (xs) -> (Opt a)`, `list.tail (xs) -> (Opt (List a))`, `list.last (xs) -> (Opt a)`: `None` on the empty list, mirroring `list.at` (`nth` already covers the failing style).
2. A built-in generic pair, not n-tuples: type `(Pair a b)`; `(pair x y)` constructs and `(pair p q)` destructures in `match`, both prelude forms like `cons`; `pair` is also a first-class function value `(Fn (a b) (Pair a b))`, so `(list.map2 xs ys pair)` works. Module `pair`: `first`, `second`, `swap`. Prints as `(pair 1 "a")`, so printed values paste back (ADR-056); structural `=`. Not a Map key or Set element: the E-TYPE message for a Pair key suggests a Str key or nested maps. A local named `pair` collides with the prelude name (ADR-047); that diagnostic suggests `p`. Triples and larger: a record with named fields (CHEATSHEET says so); nesting pairs is allowed but discouraged.
3. `list.zip (xs ys) -> (List (Pair a b))` with map2's equal-length rule (revisits ADR-045 now that a pair type exists); `map.to-list (m) -> (List (Pair k v))` in key order; `map.from-list (ps) -> (Map k v)`, a later duplicate key replaces an earlier one, like `put`.
4. Go: Pair is a two-field runtime value; differential tests cover printing, equality, patterns, first-class `pair`, zip and the map conversions.

Rejected: n-tuples (arity-indexed types and accessors, more surface); user generics (a much larger change; Pair could later be re-homed as an ordinary generic type without changing its spelling).

Who agreed: Claude proposed 1-4; agy agreed on all four and added the `pair` local-name hint, the Pair-as-key guidance, first-class `pair` and the records-over-nesting nudge, all adopted. Codex was out of usage; the owner authorized proceeding on Claude + agy agreement.
