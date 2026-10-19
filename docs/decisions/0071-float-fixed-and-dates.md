# ADR-071 Backlog 18: `float.fixed` and a pure `date` module (2026-10-19, agent consensus)

Context: Roadster Lander wrote its own number formatter, and the M9 ledger parsed dates by hand.

Decision:
1. `float.fixed x digits` (digits 0..17, a precondition): the exact binary value rounded half to even, exactly `digits` fractional digits (no point at 0), never an exponent, any finite Float; a result that rounds to zero has no sign. Unlike `float.round` (halves away from zero). A prim with exact integer arithmetic in all three runtimes, never host printf.
2. Module `date`, pure LM over Int arithmetic (no prims), proleptic Gregorian, years 1..9999, UTC only, no leap seconds: `Date` and `DateTime` records with `valid`/`valid-datetime`, `make`/`make-datetime` -> Opt; strict `parse` ("YYYY-MM-DD", exactly 10 ASCII chars) and `parse-datetime` ("YYYY-MM-DDTHH:MM:SS.mmmZ"); `print`, `print-datetime`; `to-days`/`from-days` (days since 1970-01-01, Hinnant's algorithm adapted to LM's floor division; `from-days` -> Opt); `add-days` -> Opt; `diff-days`; `weekday` (ISO 1..7); `compare`/`compare-datetime` (-1, 0, 1); `from-epoch-ms` -> Opt (floor decomposition, -1 is 1969-12-31T23:59:59.999Z) and `to-epoch-ms`; `is-leap-year`; const `ms-per-day`. Range checks come before arithmetic, so Int64 extremes give None, not overflow.
3. Durations stay plain Int; duration text and thousands grouping are deferred; "now" is `(date.from-epoch-ms (time.now-ms))` in user code.

Verification: Claude compared `float.fixed` with Python Decimal (exact value, ROUND_HALF_EVEN) on 200,000 cases including random bit patterns, subnormals and the max Float: 0 mismatches; the interpreter, Go and Python targets matched byte for byte on 2,420 more; date probes at the range ends, Int64 extremes, negative epochs, leap centuries and malformed text all came out right.

Who agreed: agy and Codex (gpt-6.1-sol) agreed; agy added `to-epoch-ms`, `compare-datetime`, `is-leap-year` and the digits precondition; Codex added Opt results at range edges, validity functions, strict parsing, floor-division adaptation and the test list. Implementation by Codex (gpt-6.1-sol), verified by Claude.
