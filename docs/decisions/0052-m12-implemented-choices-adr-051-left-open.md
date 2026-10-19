# ADR-052 M12 implemented: choices ADR-051 left open (2026-10-17)

Decided by the implementing agent (Codex) under ADR-030; one numbered item per ADR-051 item, appended as each lands.
2-3. Clock and randomness (Codex): seed text uses `[+-]?[0-9]+`
within signed Int64 bounds, accepting leading zeros, rejecting whitespace, non-ASCII digits,
hex and separators. `lm run` uses only `--seed`; `LM_SEED` is for binaries and is validated
before the entry even when no random primitive is reachable. A singleton random interval
consumes one word, following the specified algorithm. Clock origins are host-specific
(Python monotonic clock; Go process monotonic origin). Effectful fixture cases use explicit
`.cases.json` sidecars instead of LM examples; `rand-runtime.lm` avoids the stdlib `rand`
name collision under ADR-047. Each case starts at seed 0 in both backends.
1. Self tail calls (Codex): `tailcall.tail_sites` is the shared source-body walker,
returning node identities used by both the interpreter and lowering. Lowering marks
`ir.TailCall` explicitly; Go emits argument temporaries followed by next-iteration
slot assignments, with fresh lexical parameter locals inside the loop. The interpreter
uses a loop-transfer value and a fresh environment per iteration. Both retain only
argument vectors for pending postconditions, only when contracts and ensures are
present, and restore the saved invocation before checking its clauses. No language
rule was left open or changed. The old infinite-tail `recursion-limit` fixture now
uses non-tail recursion: an infinite self tail loop intentionally never exhausts the
call-depth limit. Runtime, differential and native-build fixtures pin the semantics;
`tail-contract` also pins the inner violation's node path and arguments. Measurements
are in EVIDENCE.md; ADR-051 items 4-5 are outside this change.

4. JSON (Codex): the fixed eight BadJson messages and exact cursor rules are
specified in SPEC section 8. Duplicate keys are detected after the decoded key's
closing quote, before reading its colon or value; number range errors point just
past the number token. Hex escapes use uppercase digits when printing controls;
underflow is accepted as zero/subnormal, following Float conversion. Both parsers
and printers use explicit container/token stacks (no host JSON libraries or
host recursion limit for nesting). Go's runtime owns the seven JSON constructor
pointers; generated declarations alias them so prim-produced values compare and
match exactly like LM-constructed variants, even when parse is the only reachable
JSON function. No new IR node is needed. Runtime fixtures are included in the
existing differential suite; a built stdin-driven binary pins malformed Unicode,
syntax and number diagnostics against the interpreter, including code-point
positions after non-ASCII text. These resolve item 4's unspecified diagnostic
precedence, detection cursors, control hex case and runtime representation; no
item 4 decision remains open. ADR-051 item 5 remains outside this change.
5. Real-tokenizer S5 (Claude): `bench/count_tokens.py` stays outside the `lm` package and `lm/cli_project.py` loads it only for `lm bench --tokenizer anthropic`; the key is checked before the long benchmark run (exit 1 if missing or the API fails; any other bench argument is exit 3). Framing overhead = count of a one-character message minus 1, subtracted from every count; raw and net are both recorded, ratios use net. Model `claude-opus-5-5`, API version `2023-06-01`. Texts are exactly those of the heuristic S5 (canonical LM, full Python file, bare Python). Not yet measured: this workstation has no API key (2026-10-17).
