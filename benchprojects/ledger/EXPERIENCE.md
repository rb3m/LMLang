# LM Outside-Author Experience Log (`m9-app`)

**Date:** 2026-10-16  
**Branch:** `m9-app`  
**Application:** Personal-Finance Ledger CLI (`src/ledger-*.lm`, 6 modules, 68.5 KB / ~19,097 tokens)

---

## 1. Step-by-Step Build Log, Commands, Iterations & Diagnostics

### Step 0: Orientation via Docs and Toolchain Queries
- **Commands run:**
  - `python3 -m lm index --stdlib`
  - `python3 -m lm slice colsum.main --bodies --depth 2`
  - `python3 -m lm slice colsum.summarize --bodies --depth 2`
  - `python3 -m lm slice billing.total --bodies`
- **Iterations:** 1 (0 errors).
- **Observations:** `lm index --stdlib` and `lm slice colsum.main --bodies --depth 2` immediately taught me almost every practical idiom needed for a CLI app: `io.args` pattern matching with `(list path kc vc)`, `str.to-int` returning `(Opt Int)`, `try ... (catch fs.IoError (p msg) ...)`, `(do ...)` sequencing, and record updates with `with`.

---

### Step 1: Authoring `src/ledger-model.lm` (Core Types, Money & Date Helpers)
- **Commands run:**
  1. Created `src/ledger-model.lm` (10 types, 19 pure functions, 60 examples).
  2. `python3 -m lm fmt src/ledger-model.lm && python3 -m lm test src/ledger-model.lm`
  3. `python3 -m lm edit set-purpose ledger-model.percent-used "Whole percentage of limit spent; 0 if both 0, 100 if limit <= 0 and spent > 0."`
  4. `python3 -m lm edit replace-decl ledger-model.BudgetRule '(type BudgetRule (rec (category Str) (limit Int)))'` (and 5 other record types)
  5. `python3 -m lm test src/ledger-model.lm`
- **Check/test iterations to green:** 3 iterations.
- **Diagnostics encountered:**
  1. `E-PURPOSE-LONG` on `ledger-model/percent-used/purpose`:
     ```json
     {"code":"E-PURPOSE-LONG","severity":"error","file":"src/ledger-model.lm","line":342,"col":5,"path":"ledger-model/percent-used/purpose","msg":"purpose must be one line of at most 100 characters","expected":"<= 100","found":"119","fix":[]}
     ```
     - **Fix quality:** `fix` was `[]` (expected, since shortening prose requires authoring), but `expected`/`found` (119 vs <= 100) and `path` made fixing via `lm edit set-purpose` trivial.
  2. `E-TYPE` on `ledger-model/Cents/2` (Toolchain Bug / Spec Discrepancy #1):
     ```json
     {"code":"E-TYPE","severity":"error","file":"src/ledger-model.lm","line":1,"col":1,"path":"ledger-model/Cents/2","msg":"malformed type; use Int Bool Str Unit (List T) (Opt T) (Fn (T..) R) or a declared type","expected":"","found":"","fix":[]}
     ```
     - **What happened:** I defined `(type Cents Int)` and used `Cents` as a field type inside sibling record declarations in the same module (`(type BudgetRule (rec (category Str) (limit Cents)))`, `(type Tx (rec ... (amount Cents)))`).
     - **Why the diagnostic was misleading:** It blamed `path: "ledger-model/Cents/2"` at `line: 1, col: 1` even though `(type Cents Int)` was completely valid! Using `Cents` in `fn` signatures worked fine, and referencing `CategoryTotal` (a record) inside `SummaryReport` (another record) worked fine, **only** using a type alias (`Cents`) inside a `(rec ...)` field in the same module triggered `E-TYPE` pointing at `Cents/2`.
     - **Workaround:** Used `lm edit replace-decl` on the 6 record types to use `Int` for record fields while keeping `Cents` in `fn` signatures. Immediately passed `check` and all 60 examples in `test`.

---

### Step 2: Authoring `src/ledger-parse.lm` (CSV & Strict Date Parsing)
- **Commands run:**
  1. Created `src/ledger-parse.lm` (11 pure functions, 29 examples).
  2. `python3 -m lm fmt src/ledger-parse.lm && python3 -m lm test src/ledger-model.lm src/ledger-parse.lm`
- **Check/test iterations to green:** 5 iterations (all `E-PARSE` paren-balancing in deeply nested `match` cascades before `check` ran; once parsed, `check` and `test` passed on the first try with 0 errors and 89/89 examples passing).
- **Diagnostics encountered:**
  1. `{"code":"E-PARSE","severity":"error","file":"src/ledger-parse.lm","line":266,"col":3,"path":"","msg":"unclosed `(`","expected":"","found":"","fix":[]}`
  2. `{"code":"E-PARSE","severity":"error","file":"src/ledger-parse.lm","line":1,"col":1,"path":"","msg":"file must contain exactly one top-level form","expected":"","found":"2 forms","fix":[]}`
  3. `{"code":"E-PARSE","severity":"error","file":"src/ledger-parse.lm","line":200,"col":67,"path":"","msg":"unexpected `)`","expected":"","found":"","fix":[]}`
  4. `{"code":"E-PARSE","severity":"error","file":"src/ledger-parse.lm","line":1,"col":1,"path":"","msg":"file must contain exactly one top-level form","expected":"","found":"6 forms","fix":[]}`
  - **Why this hurt:** In a function that validates 4 CSV columns + 3 date components (`parse-date` and `parse-tx-line`), there is no early-return (`?` / `Opt.and-then` / multi-binding `let-some`) in LM. Chaining 7 `match` expressions on `(Opt T)` creates 20+ closing parentheses `))))))))))))))))))))` at the end of a function. When one function has 1 too many `)` and a later function has 1 too few `(`, the module closes early mid-file and `E-PARSE` reports `"file must contain exactly one top-level form (found 6 forms)"` at `line 1, col 1` without telling you *where* the top-level module form closed!

---

### Step 3: Authoring `src/ledger-summary.lm` (Category/Month Aggregation & Top-N Ranking)
- **Commands run:**
  1. Created `src/ledger-summary.lm` (15 pure functions, 18 examples).
  2. `python3 -m lm fmt src/ledger-summary.lm && python3 -m lm test src/ledger-model.lm src/ledger-parse.lm src/ledger-summary.lm`
- **Check/test iterations to green:** 1 iteration! Zero check errors, zero test failures (107/107 examples passed on first run).

---

### Step 4: Authoring `src/ledger-budget.lm` (Budget Rules & Unbudgeted Expense Detection)
- **Commands run:**
  1. Created `src/ledger-budget.lm` (9 pure functions, 12 examples).
  2. `python3 -m lm fmt src/ledger-budget.lm && python3 -m lm test src/ledger-model.lm src/ledger-parse.lm src/ledger-summary.lm src/ledger-budget.lm`
- **Check/test iterations to green:** 1 iteration! Zero check errors, zero test failures (119/119 examples passed on first run).

---

### Step 5: Authoring `src/ledger-report.lm` (Tabular Text Formatting)
- **Commands run:**
  1. Created `src/ledger-report.lm` (10 pure functions, 12 examples).
  2. `python3 -m lm fmt src/ledger-report.lm && python3 -m lm test ...`
- **Check/test iterations to green:** 2 iterations (0 `check` errors on first try; 7 `E-EXAMPLE-FAILED` on first `test` run due to off-by-one space count in my hand-typed expected strings; fixed expected strings and passed 131/131 examples on second run).
- **Diagnostics encountered:**
  - `E-EXAMPLE-FAILED` on `format-budget-line`, `format-category-line`, `format-month-line`, `format-top-tx-line`, and the 3 `render-*` functions.
  - **Fix quality:** Even though `fix` is `[]` for `E-EXAMPLE-FAILED`, the `expected` and `found` fields printed the exact string literal produced by the interpreter, making it effortless to verify the alignment and update the example expectations.

---

### Step 6: Authoring `src/ledger-main.lm` (CLI Entry Point & I/O)
- **Commands run:**
  1. Created `src/ledger-main.lm` (1 sum type `Command`, 7 functions, 8 examples on pure functions).
  2. `python3 -m lm fmt src/ledger-main.lm && python3 -m lm test src/`
  3. `python3 -m lm edit apply '{"op":"remove-use","module":"ledger-main","use":"ledger-model"}' --in src/`
- **Check/test iterations to green:** 1 iteration to pass all 139 tests; 1 `lm edit apply` to clear `W-USE-UNUSED`.
- **Diagnostics encountered:**
  - `{"code":"W-USE-UNUSED","severity":"warning","file":"src/ledger-main.lm","line":3,"col":14,"path":"ledger-main/use","msg":"module `ledger-model` is in (use ...) but never referenced","expected":"","found":"","fix":[{"op":"remove-use","module":"ledger-main","use":"ledger-model"}]}`
  - **Fix quality:** 10/10. Passed the exact JSON from `fix[0]` to `python3 -m lm edit apply '...' --in src/` and it cleanly updated `src/ledger-main.lm` with 0 errors and 0 warnings.

---

### Step 7: Native Binary Build & Execution (`lm build`)
- **Commands run:**
  - `PATH=$HOME/.local/go/bin:$PATH python3 -m lm build ledger-main.main`
  - `./ledger-main summary examples-data/transactions.csv`
  - `./ledger-main budget examples-data/transactions.csv examples-data/budget.csv`
  - `./ledger-main top examples-data/transactions.csv 5`
- **Iterations:** 1. Built `ledger-main` (2960 KB static native binary) on the first try and produced identical output on stdout/stderr across all 3 subcommands.

---

### Step 8: Proposing Acceptance Scenarios (`tests/accept/ledger.accept`)
- **Commands run:**
  1. Created `tests/accept/ledger.accept` with 5 `proposed` scenarios.
  2. `python3 -m lm accept --review && python3 -m lm accept --guard`
  3. Updated scenarios 2 and 5 and re-ran `python3 -m lm accept --review && python3 -m lm accept --guard`.
- **Iterations:** 2.
- **Diagnostics / Spec Confusions in `.accept` files:**
  1. In Scenario 2, I originally wrote `(run ledger-summary.build-summary (ledger-parse.parse-tx-lines (list ...)))`. `lm accept --review` reported: `does not type-check: module ledger-parse is not in (use ...)`. That revealed that `(run MOD.FN ARG...)` type-checks `ARG` inside `MOD`'s scope (`ledger-summary`, which didn't use `ledger-parse`), and expects constant expressions just like `(example ...)`.
  2. In Scenario 5, I wrote `(expect (ledger-main.CmdInvalid "..."))` for `(run ledger-main.parse-args ...)`. `lm accept --review` reported: `does not type-check: refer to names of module ledger-main unqualified inside it`. Because `.accept` checks expressions inside the target function's module scope, own variants in `(expect ...)` must be unqualified (`(CmdInvalid "...")`), whereas other modules' types (`ledger-model.Tx`) are qualified!

---

## 2. Spec Confusions & Missing Documentation

1. **`.accept` file syntax and scoping rules are undocumented in `docs/SPEC.md`:**
   - Neither `AGENTS.md` nor `docs/SPEC.md` documents the grammar of `.accept` files (`(scenarios (scenario "..." (status proposed) (why "...") (run ...) (expect ...)))`) or the scoping rule that `(run MOD.FN ...)` and `(expect ...)` are type-checked *inside `MOD`'s scope* (meaning `MOD`'s own variants must be unqualified, while types from modules in `MOD`'s `(use ...)` must be qualified). I had to read an existing `.accept` file and run `lm accept --review` to discover the scoping rules.
2. **Type aliases inside record declarations (`(type Cents Int)`):**
   - `SPEC.md` Section 4 states: `alias: (type Cents Int) (transparent)`. However, using `Cents` as a field type inside `(type Tx (rec ... (amount Cents)))` in the same module fails with `E-TYPE` at `path: "ledger-model/Cents/2"`.
3. **CLI path scoping when `examples/` also exists:**
   - Running `python3 -m lm slice ledger-main.main` without `src/` loads `src/` + `examples/` (3,575 extra tokens). Passing `src/` scopes the loaded program to `src/` only.

---

## 3. Features Wanted while Authoring

1. **`opt` stdlib module (`opt.map`, `opt.and-then`, `opt.unwrap-or`) or multi-binding `(let? ...)`:**
   - Parsing CSV rows and YYYY-MM-DD dates required chaining 6–7 `(Opt T)` lookups (`field-at`, `str.to-int`, `parse-date`). Without `opt.and-then` or early return, functions pyramid-indent 20 levels deep and end with 21 closing parens.
2. **`list.sort-by` / `list.take` / `list.drop` / `list.zip-with-index` in stdlib:**
   - I had to write insertion sort (`insert-tx-by-expense`, `sort-expenses-desc`), `take-txs`, and index enumeration (`(list.range 0 (len lines))` + `field-at`) by hand.
3. **String formatting / padding in `str` (`str.pad-left`, `str.pad-right`):**
   - Building aligned CLI tables required implementing `pad-left` and `pad-right` using `list.range` + `list.map` + `str.join` and nested `str.concat` calls (since `str.concat` is binary, not variadic).
4. **Better `E-PARSE` location when a top-level form closes early:**
   - When an extra `)` closes `(module ...)` mid-file, `E-PARSE` reports `line 1, col 1: file must contain exactly one top-level form (found 6 forms)`. Reporting the line/col where the first top-level form ended (or where the second top-level form began) would save minutes of manual paren counting.
5. **Better `lm edit` ergonomics when creating a new module or adding multiple functions:**
   - `lm edit` is great for targeted single-node surgical changes (`set-purpose`, `replace-decl`, `apply`), but lacks an `init-module` op or a batch mode to add multiple declarations without invoking the CLI once per declaration.

---

## 4. Token & Byte Sizes: `lm slice` vs. Whole Files

### Whole-File Sizes (`src/*.lm`)
| File | Bytes | Lines | Approx. Tokens (`lm` count) |
|---|---:|---:|---:|
| `src/ledger-model.lm` | 10,981 B | 382 | ~3,100 |
| `src/ledger-parse.lm` | 12,994 B | 364 | ~3,650 |
| `src/ledger-summary.lm` | 17,368 B | 495 | ~4,900 |
| `src/ledger-budget.lm` | 9,598 B | 275 | ~2,700 |
| `src/ledger-report.lm` | 11,634 B | 311 | ~3,150 |
| `src/ledger-main.lm` | 5,918 B | 162 | ~1,597 |
| **Total (`src/`)** | **68,493 B** | **1,989** | **19,097 tokens** |

### `python3 -m lm slice` Output Sizes vs. Loaded Modules
| Target Symbol | Mode | Symbols in Slice | Slice Tokens | Loaded Program Tokens | Context Reduction |
|---|---|---:|---:|---:|---:|
| `ledger-main.main` | signature slice (default) | 13 | **808** | 19,097 | **95.8% smaller** |
| `ledger-main.main` | `--bodies` (depth 1) | 13 | **1,706** | 19,097 | **91.1% smaller** |
| `ledger-report.render-budget-report` | signature slice (default) | 19 | **1,244** | 14,320 | **91.3% smaller** |
| `ledger-summary.build-summary` | signature slice (default) | 14 | **999** | 9,226 | **89.2% smaller** |
| `ledger-parse.parse-tx-lines` | signature slice (default) | 11 | **831** | 7,966 | **89.6% smaller** |
| `ledger-budget.evaluate-full-budget` | signature slice (default) | 10 | **738** | 11,287 | **93.5% smaller** |
