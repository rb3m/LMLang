# Evidence log (feeds the M6 gate)

Append dated datapoints; method notes stay with each entry. Token counts use the ADR-012 heuristic (`lm.index.tokens`). These are single-project spot checks, not the benchmark.

| Date | Metric | Datapoint | Method |
|---|---|---|---|
| 2026-10-15 | S1 slice size | `shapes.scale` slice 152 tokens vs 923 loaded (16%); `list.sum --bodies` 137 vs 588 | `lm slice SYM` stderr line; "loaded" = canonical text of every loaded module incl. stdlib deps |
| 2026-10-15 | S2 edit output | `replace-body shapes.longest-side <expr>` 44 tokens vs 513 for regenerating shapes.lm (9%); `rename` 6 (1%); `add-fails` 8 (2%); `set-purpose` 15 (3%) | tokens of the command line vs tokens of the full file |
| 2026-10-15 | S3 invented names | static checker rejects unknown names, unknown modules, unexported names, missing `use`, unknown effects/errors/fields (fixtures in tests/spec/check); rate on injected corpus not yet measured | M6 builds the injected-hallucination suite |
| 2026-10-15 | Bug class found by edit tests | cross-module type in a signature + alphabetical module order exposed a resolver pass-order bug that unit fixtures had missed | ADR-022 |
| 2026-10-15 | M6 full run | S1 3.6% (47% vs module alone), S2 8.9%, S3 100% (43/43), S4 10/13 first try and 13/13 within 2, S5 1.37x (miss), S6 6/6 | `lm bench`; ADR-024 |
| 2026-10-15 | Semantics slip caught by equivalence only | "mean rounded toward zero" vs floor division; passed check and test | bench/tasks/03-stats |
| 2026-10-16 | M8(e) real script | `examples/colsum.lm` (11 fns, 9 examples) written by Claude: 2 check iterations. Found and fixed a resolver bug (a record/sum type mentioned by an earlier type or error was rejected as "malformed type"; fixture `type-forward-ref`), and an off-by-one in field reference paths that would have made `rename` edit the wrong atom. Unclosed-paren E-PARSE pointed at line 1 (backlog 10). Native binary 2.8 MB; 200k rows in 0.14 s, output identical to a Python reference; 20k rows 0.026 s compiled vs 1.55 s interpreted | ADR-038 |
| 2026-10-16 | Cross-agent review | Codex found 2 real backend bugs the 173-example differential test missed (comparison operand order; function equality); agy found 4 stdlib API traps (argument order, Opt vs fail for to-int, naming) | ADR-037 |
| 2026-10-16 | M8(e) macOS | M1 Mac Mini: 99 unit tests pass with Go 1.27.2 (Homebrew Python 3.15; `lm check` also runs on stock /usr/bin/python3 3.9.6); cross-built darwin/arm64 `colsum` and a native build give identical output, 0.22 s for 200k rows | the owner's Mac Mini, fresh clone of origin |
| 2026-10-16 | Outside author (S1, S4) | agy (not the toolchain author, learning only from AGENTS.md, SPEC and `index/slice/explain`, without reading lm/) wrote a 6-module ledger CLI: 1,989 lines, ~19,100 tokens, 139 examples, built natively and run. Check/test iterations to green per module: 3, 5, 1, 1, 2, 1 (parse module: all 5 were paren balancing in nested `match`; report module: 7 hand-typed expected strings off by a space). Slices: 89-96% smaller than the loaded program (`ledger-main.main` 808 vs 19,097 tokens). First S1 datapoint on a project of the size ADR-024 asked for; caveat: written by an LLM, not a human, and it is one project | branch m9-app, EXPERIENCE.md there; ADR-044 |
| 2026-10-17 | M10 `let?` rewrite (S5 input) | m9-app `src/ledger-parse.lm` rewritten with `let?`, `list.get` and `opt.map` (bodies of `field-at`, `parse-budget-line`, `parse-date`, `parse-tx-line` only; the other 7 fns unchanged); all 89 examples of ledger-parse + ledger-model still pass. File: 2,768 -> 2,581 tokens (-6.8%), 350 -> 271 canonical lines, max paren depth 25 -> 19 (now set by the untouched fold in `parse-tx-lines`). The 4 rewritten bodies: 776 -> 588 tokens (-24%); body depth `parse-date` 22 -> 8, `parse-tx-line` 20 -> 9, `parse-budget-line` 14 -> 8, `field-at` 6 -> 2. S5 (benchmark) not re-run: still OPEN | copies of both files outside the repo; `lm.index.tokens` on the canonical file text; depth = nested lists in `lm.sexpr.read`; ADR-045 item 5 |
| 2026-10-17 | M11 Map/Set: `colsum` migrated (ADR-049 item 6) | `examples/colsum.lm` groups with a `(Map Str Int)` (`map.update`), output now in key order. Tokens 1,421 -> 1,225 (-14%; `add-to` and its 2 examples removed, `render` takes key and total). Native binary, 200,000 rows (Linux amd64, `/usr/bin/time`): 5 keys 0.13 s -> 0.14 s; 49,056 distinct keys: old linear scan did not finish (killed after 18 min; prefixes of the same file: 2,500 rows 7.9 s, 5,000 rows 70 s, 10,000 rows 392 s), new 0.40 s. Outputs equal a Python reference (first-seen order before, sorted after) in every run that finished | CSVs generated outside the repo (seeded); `lm.index.tokens` on the file; ADR-050 item 7 |

## 2026-10-17 — ADR-051 item 1: self tail calls

Local Linux measurements, contracts enabled, Python 3.14 and the installed Go toolchain.
These are wall times, not a benchmark gate. Interpreter comparison loads `HEAD:lm/interp.py`
for the before version and the working-tree interpreter for after, with the same checked
`examples/colsum.lm`, `StringIO` output and `runner.in_big_stack`; load/check excluded.

| Work | Before | After |
| --- | ---: | ---: |
| `colsum.print-all`, 1,000 identical rows | 0.0130 s | 0.0133 s |
| `colsum.print-all`, 5,000 identical rows | 0.1114 s | 0.0420 s |
| Tail loop through if/let/let?/do/match, 1,000,000 steps, interpreter | E-RECURSION-LIMIT | 12.4981 s |
| Counter, 10,000,000 steps, native binary | not measured | 0.2036 s median (0.2004–0.2052 s, 3 runs) |

The million-step fixture failed with E-RECURSION-LIMIT before implementation and now
returns `(Some 1000000)`. Native timing includes process startup, excludes build time.
`print-all` still copies tuple tails; loop conversion removes retained recursive frames
and does not change that list representation. The old colsum `add-to` was non-tail
recursion (ADR-050 item 7), so these results do not claim to fix or remeasure it.

## 2026-10-17 — ADR-054: Roadster Lander (backlog 11)

Written by Codex in LM from AGENTS.md, CHEATSHEET and ADR-054 only; verified by Claude. 6 modules, 734 lines, 86 examples, 8 proposed scenarios. Check/test cycles to green: physics 4, autopilot 3, grade/levels/main 1 each. No toolchain bug found. Gaps: no `float.ln`/`exp` (the game sums -ln(1-x) as a series, like the 1969 original); no `lm edit` op to create a module (empty modules were scaffolded by hand). A game bug was caught by examples before review: a tiny burn (1e-308 kg/s) made `fuel/burn` overflow to the fault E-FLOAT. Review found the first scenarios opaque (`expect true` from a grab-bag checker); rewritten to show numbers. Native binary 3.0 MB (macOS arm64), output identical to the interpreter; a short transcript ran in 2.7 ms native vs 47 ms interpreted (Codex, 15-run medians, includes startup).

## 2026-10-18 — ADR-057: Float math core set (backlog 13)

16 functions in `float` (pi, e, exp, ln, log2, log10, pow, cbrt, hypot, sin, cos, tan, asin, acos, atan, atan2), shipped in 4 pieces by Codex (gpt-6-astra, medium effort), each verified by Claude. Ports of Go's pure-Go exp/ln and FreeBSD msun (compensated log2/log10, pow, cbrt, hypot, Payne-Hanek trig reduction, inverse trig) as twin Python/Go implementations; no libm, every Go step wrapped in `float64()` against FMA. Max error against 60-digit Decimal vectors: 0 ulp for ln/log2/log10, 1 ulp for the rest (about 6,000 vectors, including subnormals, max float, `1e22` and the reduction worst case 6381956970095103*2^797). Python and Go bit-identical on all vectors; native arm64 binaries matched the interpreter on 120 sampled values. Gap found: Go's literal log2/log10 exceeded 1 ulp (`log10(1e15) = 14.999999999999998`), so msun's compensated versions were used. Codex hit its usage limit twice and resumed its session after each reset.

## 2026-10-18 — ADR-058/059: constants and pairs, designed and built while Codex was out of usage

Claude + agy consensus (owner-authorized without Codex). agy implemented both; Claude's review of constants found three bugs agy's own fixtures missed because they declared constants in a convenient order: alphabetical check-time evaluation crashed `lm check` with a Python TypeError when a constant used a later one, Go init order was wrong for constants reached through function bodies, and examples created false E-CYCLE errors. All fixed with regression fixtures. Pairs passed review first time (one hint reworded). Float math extras (log1p, expm1, sinh, cosh, tanh; Codex) brought `float` to 21 functions, all <= 1 ulp. Roadster Lander's `minus-log` moved from its series to `float.ln` (2e-13 m/s worse from rounding 1 - x) and then to `float.log1p` (bit-identical to the series). After the merges: 171 unit tests, 696 differential examples identical interpreted and native.

## 2026-10-18 — ADR-060/061: S5 from 1.34x to 1.28x (heuristic, still open)

Finding: S5 is the median of per-task ratios (median task 01-cart), so the "outliers" greet (1.76x) and roman (1.40x) barely moved it. A roman rewrite with const + Pair was longer (282 -> 352 tokens); `(pair 1000 "M")` repeated 13 times costs more than two parallel lists. agy's analysis (re-measured by Claude): examples 24% of LM tokens, purposes 18%, sigs 13%, module headers 8%; optional exports alone would give 1.295. Built: `for` (greet 148 -> 126), optional exports, proven-safe division/indexing (removed spurious `fails`), inferred lambda types; bench programs rewritten. agy's rewrite also cut purposes 59% (to one-word labels such as "Deposit."), an apparent 1.15x; Claude restored them because the Python baseline keeps its docstrings. Honest result: 1.28x (1.27x with punctuation runs merged), S3 42/43 unchanged after retargeting one mutation the language made obsolete, equivalence 13/13. Review of the fact system found a soundness bug (stale facts reused by a constant in another module), caught at runtime by the E-PROOF-VIOLATED net and fixed. Official S5 still awaits the real-tokenizer re-measure.

## 2026-10-18 — ADR-062: Python build target

`lm build --target py` (agy, two pieces; reviewed by Claude). The whole build-fixture set (38 runs) and differential corpus run identically on the Python target from a directory outside the repo. Roadster Lander: a 57 KB Python script vs a 3 MB Go binary, byte-identical output on a scripted 19-turn game. Seeded `rand` + Map + float math: interpreter, Python script and Go binary identical. Review caught two parity gaps agy's tests missed because they compared parsed JSON: diagnostic key order/spacing differed from Go, and a malformed `LM_SEED` was not rejected; both fixed with a byte-level assertion. Runtime code is embedded mechanically from the real `lm/` sources, only the parts a program reaches. Not yet run on DreamHost itself.

## 2026-10-18 — ADR-064: Outside-author project scale (backlog 9)

Measured S1 and S2 on the two multi-module outside-author projects using `lm bench --project PATH` (reusing the exact frozen settings and definitions of the 13-task benchmark in `lm/bench.py`):
- `benchprojects/ledger`: 6 modules, 76 functions, 16,667 total tokens.
  - S1 (slice vs project text): median 2.0%, max 7.5% (vs 13-task benchmark median 4.4%, max 7.4%).
  - S1 module-relative (slice vs target fn's own module): median 10.2%, max 56.4% (vs 13-task median 56.0%, max 129.9%).
  - S2 (edit op vs target module): median 2.2%, max 15.7% (vs 13-task median 10.4%, max 27.9%).
- `games/roadster-lander`: 6 modules, 44 functions, 8,755 total tokens.
  - S1 (slice vs project text): median 3.9%, max 8.5%.
  - S1 module-relative: median 17.0%, max 103.2%.
  - S2 (edit op vs target module): median 3.7%, max 43.4%.

Caveats (per ADR-064):
1. Prior familiarity: the projects were written by AI agents with prior knowledge/exposure (agy authored the M9 ledger while familiar with LM; Codex authored Roadster Lander from AGENTS.md, CHEATSHEET and ADR-054), not completely blind outside authors.
2. S2 metric definition: S2 measures replacement payload size (`replace-body` edit command tokens vs target module tokens), not the total tokens in an agent's prompt/completion exchange.


## 2026-10-19 — ADR-065: cold start outside the repo (backlog 22)

A fresh Codex session (gpt-6.1-sol, medium effort, `codex exec -s workspace-write`) in an empty directory outside the repo; PATH held a symlink to `bin/lm` plus Homebrew Python/Go and /usr/bin. It was told to use only `lm` and files it created, and was given a fixed word-frequency CLI spec (ASCII alphanumeric runs, lowercased, count desc then word asc, top N default 10, exit statuses 2/2/1 for usage/bad N/unreadable file). Result kept as `benchprojects/wordfreq` (1 module, 145 lines, 32 examples, 13 proposed unapproved scenarios, its own EXPERIENCE.md and an 18-case native CLI check).
- Isolation: none of its 28 shell commands touched the repo (checked in the transcript); it listed the experiment's parent directory once.
- Docs read: AGENTS.md, `lm guide`, `help edit/accept/run/build`, `index`, `index --stdlib`, 3 starter slices: about 28 KB, about 8.5k heuristic tokens (ADR-012; `lm.index.tokens`, an estimate, not the S5 tokenizer). `index --stdlib` alone is 15 KB (54%).
- Cycles: first explicit `lm check`/`lm test` green; 3 cycles in all, none failing. All code written through `lm edit` (driven from small Python scripts); one `add-decl` refused with E-PARSE (raw newline inside a string) and retried.
- Session total: 46,286 tokens (Codex's count, including reasoning and output).
- Verified by Claude: check, test and guard green; native binary output and exit statuses match the spec on all six behaviors tried.
- Gaps: guessed `(allow io.out fs.read)`, rejected only by `accept --review` while `check`, `test` and `accept --guard` stayed green (confirmed, backlog 24); a scenario must allow every effect the target declares; `lm run` prints the returned Int and exits 0 (now documented); errors went to stdout because the guide did not mention `io.eprint` (now added). Setup gaps: stock macOS python3 3.9 crashed (now a clear message); Codex's read-only default sandbox made `lm new` fail with a traceback (now a message).
- Caveat: Codex has written LM before (Roadster Lander) in other sessions; this session had no repo context, but the model is not naive to LM.
