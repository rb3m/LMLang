# Testing — machine layers and the human oracle

Humans mostly do not read the code. The project owner (the human who approves scenarios in your checkout) confirms *intent*. The agent's job is to make that cheap and to make silent drift impossible.

## Layers

1. **Unit tests** (`tests/unit`, `python3 -m unittest discover tests/unit`): toolchain correctness. Agent-owned.
2. **Spec fixtures** (`tests/spec`): one per SPEC rule and per diagnostic code; asserts the exact code is emitted. Agent-owned.
3. **Language-level tests**: `example`, `requires`, `ensures` inside LM code, run by `lm test`. Agent-owned.
4. **Golden files** (`tests/golden`): fmt/index/slice/explain outputs. Agent-owned; regenerate only with `UPDATE_GOLDEN=1` and review the diff.
5. **Acceptance scenarios** (`tests/accept/*.accept`): **human-owned oracle**. See below.
6. **Compiled differential** (`tests/unit/test_gobackend.py`, `test_pybackend.py`): pure examples compiled to Go and Python must give the interpreter's outcome; effectful examples with `given` are excluded. Real-effect runtime cases remain included. `tests/spec/build/` fixtures pin built binaries (exit codes, stdout, stderr). Go tests skip with a visible `SKIP:` line when Go is absent.
7. **Benchmark** (`bench/`): thesis metrics S1-S6 (`lm bench`). Agent runs; human reads `bench/results/summary.md`.

## Benchmark (`lm bench`)

`bench/tasks/NN-name/` holds `name.lm`, `name.py` (equivalent Python with type hints, docstrings, `_examples()` and contract asserts) and `cases.json` (shared cases; args use JSON, records as `{"$new":"Type",field:..}`, variants as `{"$v":"Name","args":[..]}`, optional `py_want`, `py_args`, `out`). `lm bench` checks that both implementations satisfy every case, then measures S1-S6 and writes `bench/results/summary.md` and `results.json`. `bench/results/s4-attempt1.json` is the frozen record of which tasks were green on the first try (do not regenerate it; it is evidence). The injected-error list is `H` (hallucinations, S3) and `LOGIC` (logic bugs, reported separately) in `lm/bench.py`. Token counts: ADR-012. `lm bench --tokenizer anthropic` (dev-only, ADR-051 item 5) also counts the canonical LM text and the full and bare Python with the Anthropic `count_tokens` endpoint (`bench/count_tokens.py`, `ANTHROPIC_API_KEY`; it fails rather than fall back), subtracts the measured framing overhead, writes `bench/results/s5-anthropic.json` (model, API version, framing, source hashes, raw and net counts) and appends a separate section to the summary.

## Acceptance scenarios

With no PATH arguments, `lm check` also validates tests/accept/*.accept without executing scenarios: file syntax and shape, target visibility, argument and expectation types, error fields, and known effect permissions covering every declared target effect. Problems are JSON E-SCENARIO errors with the file, line and scenario name; suggestions appear in the message rather than an inapplicable edit fix. `lm accept --guard` rejects every malformed scenario, proposed or approved, with `INVALID   NAME: problem`, without execution, in addition to the existing lock checks.

Format (s-expr; the reader accepts one top-level form per file, so each `tests/accept/*.accept` file is `(scenarios (scenario ..) ..)`):
```
(scenarios
  (scenario "Order with tax"
    (status proposed)                     ; proposed | approved
    (why "A Mexican order of 100 and 200 cents totals 348 with 16% VAT.")
    (run billing.total (list 100 200) "MX")
    (expect 348)))
```
Exactly one of: `(expect VALUE)`, `(expect-fail Err args..)` (qualified error name, e.g. `billing.BadRegion "US"`), `(expect-out "text")` (needs `(allow io.out)` before `run`). Scenario `run` arguments, `expect` values and `expect-fail` arguments are external constants with no own module: module-defined variants, record/type names in `new`, and errors must always be qualified, including names from the target function's module (e.g. `(shapes.Circle 2)`). The rule applies throughout nested values; prelude names (`Some`, `None`, `list`, `mapof`, `setof`, `DivZero`, `OutOfRange`, literals) stay unqualified. Arguments and expected values are type-checked against the function signature; an unqualified target-module name is E-NAME-UNRESOLVED and a FAIL, not a crash. Module source and examples still use unqualified own names. Names are unique. Malformed scenarios print as `BAD`/`FAIL` and fail the run.

Lock mechanics (implemented in `lm/accept.py`): the digest is sha256 (16 hex chars) of the scenario's canonical flat text with the `status` clause removed, so approving does not change it but any edit to name, why, run or expectation does. `accept.lock` lines are `<digest> <name>` with an optional `\t# approved YYYY-MM-DD by owner: "TEXT"` suffix. `--guard` fails on: `CHANGED` (digest differs), `MISSING` (locked but gone), `UNAPPROVED` (locked but no longer approved), `UNBLESSED` (approved but not locked). `--guard` accepts lines with or without the evidence suffix. `lm accept --approve DIGEST.. --by "TEXT"` records owner approval by updating `(status proposed)` to `(status approved)` and writing the evidence-bearing lock line without requiring a TTY. `lm accept --retire NAME.. --by "TEXT"` removes the lock lines of scenarios that no longer exist (renamed or deleted), only after the owner agrees; it refuses a name that is not locked or whose scenario still exists, touches no other line, and the owner's words go in the commit's `Approved-by-owner:` trailer. Interactive `lm accept --bless` remains available for humans who prefer it; it preserves existing suffixes of unchanged entries. Flags `--dir` and `--lock` exist for tests.

Rules (enforced by tooling and by AGENTS.md):
- The agent writes scenarios as `proposed` and never approves on its own judgment or hand-edits `accept.lock`.
- `accept.lock` stores a hash of each approved scenario. `lm accept --guard` fails if an approved scenario changed or disappeared. The agent runs `lm accept --approve` only after explicit owner approval in conversation.
- Only `approved` scenarios count toward S6; `proposed` ones are reported as "needs your OK".
- Scenarios are written in domain terms with a one-sentence `why`, so a human can judge them in seconds without reading LM.

## Approval protocol (ADR-055, AGENTS.md rule 5)

Per scenario the AI shows name, why, what is run in plain words, the expected result, what the program does today, and for a modification the before/after. It asks for an explicit answer. Clear assent ("approved", "yes", "bless them", an emoji the owner has declared as a blessing, ✅ by default) counts; anything ambiguous is asked again; partial answers approve only what was named. Once the owner explicitly approves, the AI runs `lm accept --approve DIGEST.. --by "<their words>"`. A modified scenario returns to `proposed` and needs a new approval. The AI never approves on its own judgment, never on another agent's word, and never to make a failing guard pass.

## Human routine (about 5 minutes)

```
python3 -m lm accept --review     # lists proposed scenarios as a checklist with digests and what the program does today
# owner approves in conversation; agent runs lm accept --approve DIGEST.. --by "<words>"
# (or human can edit status proposed -> approved and run interactive lm accept --bless)
python3 -m lm accept              # plain report: PASS/FAIL per scenario, summary line
python3 -m lm explain billing.total   # plain-language description + examples table
```
Report shape:
```
PASS  approved  Order with tax          billing.total(...) = 348
FAIL  approved  Empty order rejected    expected EmptyOrder, got 0
----  proposed  Unknown region          needs your OK
Summary: 8 approved (7 pass, 1 FAIL) · 3 proposed · guard OK
```

## What the human should try by hand

1. Run `lm accept` after each milestone; any FAIL on an approved scenario is a regression.
2. Run `lm explain` on a function you care about; does the "purpose / takes / returns / fails / examples" text match your intent?
3. Try to break it: invent an input the examples did not cover and run `lm run mod.fn args`. If the result surprises you, tell the agent the input and the expected result; it becomes a new proposed scenario for you to approve.
4. Skim `bench/results/summary.md` at M6 for the gate decision.

## Agent obligations

- Before declaring any task done: `lm check`, `lm test`, `lm accept --guard`, unit tests, all green.
- Every bug fix adds a spec fixture or example that fails before the fix.
- Never edit or delete an approved scenario or `accept.lock`.

Golden query commands run in a temporary project containing only the repository's
`examples/` and `stdlib/` paths (`tests/unit/golden_support.py`). Local `src/`
programs cannot change these snapshots. Regenerate with `UPDATE_GOLDEN=1` and
review the resulting diff.

### Examples with effects

Examples on functions declaring effects use `(example (ARGS...) (given CLAUSE...) => RESULT CHECK...)`; `given` is required, even when empty, and forbidden on a pure function. For example, a function that reads stdin and prints it may have `(example () (given (stdin "hello")) => unit (out "hello\n"))`. Example values resolve names in their own module, unlike external scenario values. Exported effectful functions still do not need examples (R-L6).

`given` supports `args`, `stdin`, `env`, `file`, `dir`, `now-ms` and `seed`. Every example gets fresh empty args/stdin/env/files, roots `.` and `/`, both clocks frozen at 0, and seed 0; nested calls share this world. Declare parent directories for children; declarations may appear in any order. Paths use non-empty `/`-separated components, optionally an absolute `/` prefix, with no empty/`.`/`..` component, trailing `/` or NUL. `/` addresses the absolute root; `.` is only an implicit root, not a valid path. The fake tree models regular files and directories; symlinks, permissions, encoding failures, cross-device operations and races are outside its scope. No fake operation touches host files, environment, clocks or streams.

After comparing the value or expected recoverable `(fail Error fields...)`, the runner checks exact `out`/`err` text and `file`, `no-file`, `dir`, `no-dir` state. For `io.out` functions, an omitted `out` or `err` asserts an empty stream. Captures include program-added newlines but exclude runner diagnostics and rendered results. Contracts stay enabled and faults cannot be expected. Mismatches are E-EXAMPLE-FAILED. See SPEC sections 5 and 12 for clause arities, constant types, effect coverage and E-EXAMPLE validation.

`lm test` runs these examples only in the interpreter and includes them in example totals. They round-trip through fmt/slice/explain. Add check fixtures for each validation error, run fixtures for passing and failing outcomes, and unit coverage proving host files, environment and stdout remain untouched. Compiled differential enumeration excludes fake-world examples for both targets; it continues to cover ordinary pure examples and real-effect runtime cases below. Acceptance scenarios retain their existing human approval and real-effect execution rules.

### Effectful runtime fixtures (ADR-051)

Real-effect cases remain available independently of fake-world examples.
A runtime fixture may add `NAME.cases.json` beside `NAME.lm`, mapping zero-argument function names
to `{"expected": "LM value text"}` or `{"kind": "fault", "expected": "E-CODE"}`
(`kind` defaults to `ok`; `fail` uses `(fail Err args...)` text).
`lm test` runs these explicit cases with each function's declared effects and contracts enabled,
a fresh interpreter and seed 0, and compares the outcome. A mismatch is E-EXAMPLE-FAILED.
They are counted separately from examples. The Go and Python differential harnesses include the same cases,
resetting seed 0 before every call and comparing their outcomes with the interpreter.
`rand-runtime.lm` avoids colliding with stdlib `rand.lm` (ADR-047); its cases also test clocks using
boolean sanity checks rather than comparing host timestamps.

## Fixture layout and commands

Unit tests: `python3 -m unittest discover tests/unit` (~70s with Go on PATH). Spec fixtures: `tests/spec/fmt/NAME.{in,out}.lm`; `tests/spec/diag/NAME.lm`+`.expect` (parse-level codes; optional `.position` = line col); `tests/spec/check/NAME.lm`+`.expect` (module name = file stem, `.expect` = space-separated codes, empty = clean) and `tests/spec/check/DIR/` multi-module cases with an `expect` file. Edit tests run the CLI in a temp project (`cwd` = project, `PYTHONPATH` = repo). Goldens: fixed examples + stdlib project (`tests/unit/golden_support.py`), `tests/golden/*.txt` (regenerate with `UPDATE_GOLDEN=1`, review the diff). Samples: `examples/billing.lm`, `examples/shapes.lm`. Runtime fixtures: `tests/spec/run/NAME.lm`+`.expect` (codes from `lm test`); `semantics.lm` there is the executable semantics spec. Effectful runtime cases use `NAME.cases.json` (docs/TESTING.md); seed 0 resets per case. New check/runtime rule => new fixture first. Sample program: `examples/billing.lm`.
