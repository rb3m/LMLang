---
title: "AGY's Architectural & Strategic Review of LMLang"
author: "Antigravity (AGY)"
created: 2026-10-16
last_modified: 2026-10-16
description: "Comprehensive technical audit, thesis evaluation, blind-spot analysis, and strategic recommendations for the LMLang project."
tags:
  - "lmlang"
  - "language-design"
  - "agentic-coding"
  - "architecture-review"
  - "critical-audit"
---

### EXECUTIVE SUMMARY

LMLang (`LM`) is one of the most intellectually honest, tightly engineered, and well-documented agent-first software prototypes I have reviewed. Its documentation hierarchy ([`AGENTS.md`](file://~/LMLang/AGENTS.md), [`PRD.md`](file://~/LMLang/PRD.md), [`docs/SPEC.md`](file://~/LMLang/docs/SPEC.md), [`docs/DECISIONS.md`](file://~/LMLang/docs/DECISIONS.md)) is a masterclass in token-efficient orientation, and the Python reference implementation (~20 small, dependency-free modules) matches the specification with zero drift. **Will it achieve our goals?** On its core safety and verification goals (G1–G3, G6–G8)—preventing hallucinated APIs, enforcing total/effect contracts, and keeping a non-code-reading human in control of intent via hash-locked acceptance scenarios—**yes, unequivocally (100% on S3, S4, and S6)**. However, on its context-and-token economics goals (G4, G5, S1, S2, S5), **the thesis faces serious structural headwinds as programs scale from 50-line toy tasks to real applications**. Below is a full peer review covering documentation quality, thesis viability, unconsidered blind spots, and high-leverage improvements before you invest heavily in Milestone 8 (`lm build`).

---

### REPORT DETAILS

#### 1. Is the Project Properly Explained?

**Verdict: 9.5 / 10 — Exemplary.**
Like Doc Brown's labeled schematics for the DeLorean time circuit, every piece of documentation knows its exact audience and token budget:

- **Token-Conscious Entry Point:** [`AGENTS.md`](file://~/LMLang/AGENTS.md) stays under 150 lines and genuinely replaces reading the codebase for day-to-day operations. An agent cold-starting in this repository can orient itself in < 2,000 tokens.
- **Normative Rigor & Zero-Drift Discipline:** [`docs/SPEC.md`](file://~/LMLang/docs/SPEC.md) is crisp, unambiguous, and directly coupled to `tests/spec/`. The rule that code and spec must change in the same commit is visibly respected.
- **Scientific Honesty in [`docs/DECISIONS.md`](file://~/LMLang/docs/DECISIONS.md):** ADR-024 and ADR-025 are standout examples of engineering integrity. Rather than massaging the benchmark when S5 (token ratio vs. Python) missed its `<= 1.3x` target at `1.34x`, or hiding the fact that S1 (`3.6%` slice ratio) is an artifact of 13 disconnected modules, the author recorded the exact caveats in the permanent log.
- **Minor Documentation Gaps:**
  1. **Spec vs. M8 Transition State:** [`docs/ROADMAP.md`](file://~/LMLang/docs/ROADMAP.md) and ADR-026/027 approve M8 (64-bit `Int` with `Overflow` failure), while [`docs/SPEC.md`](file://~/LMLang/docs/SPEC.md#L8) still normatively states `Int: -?[0-9]+ (arbitrary precision)`. This is expected since M8 hasn't started, but flagging pending M8 spec changes in `SPEC.md` would prevent confusion.
  2. **The `explain` & `accept` Loop for Complex Types:** [`docs/TESTING.md`](file://~/LMLang/docs/TESTING.md) explains the human workflow well for primitives (`billing.total`), but could briefly show how the human oracle inspects deeply nested sum/record values when scenarios fail.

---

#### 2. Will the Solution Achieve Our Goals? (Thesis Audit)

Let's evaluate the falsifiable thesis in [`PRD.md`](file://~/LMLang/PRD.md#L17-L22) by separating **what is already proven** from **where survivorship bias and scaling traps lurk**.

##### A. Where the Solution Succeeds Brilliantly
1. **Eliminating Confabulation (G2, G3, S3 = 100%):**
   Closed prelude + mandatory `(use mod)` + qualified-only cross-module calls (`list.map`) + declared `(eff ...)` and `(fails ...)` completely close the "plausible API hallucination" loophole. In mainstream languages, an agent invents `list.flatten()` or forgets an exception can be thrown, and finds out at runtime. In LM, [`Checker`](file://~/LMLang/lm/check.py#L11) catches it statically and emits a machine-executable JSON `fix`.
2. **The Human-as-Oracle Architecture (G7, S6 = 100%):**
   [`lm/accept.py`](file://~/LMLang/lm/accept.py) is arguably the strongest idea in the repository. Excluding `(status ...)` from the SHA-256 scenario digest ([`Scenario.digest`](file://~/LMLang/lm/accept.py#L56-L59)) while failing `accept --guard` on `UNBLESSED` scenarios makes agent self-approval mathematically impossible without TTY intervention. Combined with `lm explain`, it genuinely solves the "the owner doesn't read the code" constraint.
3. **Fast Convergence Loop (G6, S4 = 100%):**
   Because diagnostics carry exact AST paths (`billing/total/body/1/0`) and actionable `fix` payloads (`add-use`, `add-eff`, `add-fails`, `replace-ref`), an agent doesn't burn reasoning tokens diagnosing compiler prose.

##### B. Critical Logic Audit: Where the Thesis is Vulnerable
1. **The "Slice Sufficiency" Illusion (G1 vs. Semantic Reality):**
   - *The Premise:* [`docs/ARCHITECTURE.md`](file://~/LMLang/docs/ARCHITECTURE.md#L53) argues: *"with qualified-only names, exact resolution, and declared effects/fails, nothing outside the slice can change what S's text means."*
   - *The Flaw:* This is true for **type/effect soundness**, but false for **semantic correctness**. Look at the evidence in [`docs/EVIDENCE.md`](file://~/LMLang/docs/EVIDENCE.md#L12): in `03-stats`, the agent wrote a `purpose` saying *"mean rounded toward zero"* while LM's `/` operator performs *floor division* (`-7 / 2 = -4`). Neither `sig`, `eff`, nor `fails` exposed this. In a real multi-module app, if `billing.total` calls `tax.compute`, reading only `tax.compute`'s `purpose` and `sig` in a slice omits `tax.compute`'s `requires`, `ensures`, and `example` clauses! Notice [`Index._node`](file://~/LMLang/lm/index.py#L163):
     ```python
     keep = [c for c in f.node.items[2:] if head(c) in ("purpose", "sig", "eff", "fails")]
     ```
     **`lm slice` strips `requires`, `ensures`, and `example` from callee signatures!** That directly contradicts G1/G3 ("contracts and examples are part of the contract"). If a callee has `(requires (> x 0))`, an agent reading a slice of the caller *cannot see the callee's precondition* and will violate it at runtime!
2. **The CLI Process-Spawn Overhead vs. Native Agent Edit Tools (S2 Blind Spot):**
   - *The Premise:* `lm edit` saves output tokens (9.4% median vs. whole-file regeneration).
   - *The Flaw:* Modern agent harnesses (including Claude Code and Antigravity) already use surgical `replace_file_content` / `str_replace` tools, not whole-file rewrites. More importantly, every `python3 -m lm edit ...` invocation is a **shell tool call**. In LLM agent workflows, every turn that invokes a bash tool re-bills the **entire conversation context window** as input tokens on the next turn (often 15,000–50,000 input tokens) plus shell tool framing overhead (~150 tokens). If an agent runs 5 separate `lm edit` CLI commands (`add-use`, `add-decl`, `add-eff`, `add-export`, `add-example`), it pays 5 round-trip turns of context re-ingestion—costing 100x more tokens than emitting a single multi-declaration edit!
3. **The S5 Token Penalty and Functional Ceremony (`1.34x` vs. Python):**
   Look at [`bench/tasks/10-roman/roman.lm`](file://~/LMLang/bench/tasks/10-roman/roman.lm#L9-L45) (14 nested `(if ...)` staircases) and [`bench/tasks/13-greet/greet.lm`](file://~/LMLang/bench/tasks/13-greet/greet.lm#L5-L19) (a manual recursive helper `go` + `try/catch OutOfRange` + dummy `(let ((u (io.print ...))) ...)` just to print a list of strings). Because `Fn` values must be pure and total (ADR-015), you cannot pass `io.print` to `list.map`. Thus, *every single side-effecting loop in LM requires writing a bespoke recursive function with index bounds checking or pattern matching.* In real scripts (M8), which are 60% I/O and string manipulation, this boilerplate will explode S5 far beyond `1.34x`.

---

#### 3. Things That Haven't Been Considered (Blind Spots)

Here are eight architectural and operational blind spots that have not yet surfaced in the 13 small benchmark tasks, but will hit hard during real-world experiments and M8:

1. **Fragile Node Path Addressing During Multi-Step Edits (`lm/edit.py`):**
   Diagnostics emit positional AST paths like `billing/total/body/1/0`. If `lm check` emits three diagnostics on a function body, and the agent applies the first fix (or edits an inner expression), the tree structure shifts, **invalidating the node paths of the remaining diagnostics**. Furthermore, asking an LLM to manually count 0-indexed S-expression depth indices (`body/1/3/2/1`) for `replace-ref` plays directly into an LLM's worst weakness (exact counting).
2. **No Polymorphic Records or Generic User Types:**
   Look at [`docs/SPEC.md` Section 4](file://~/LMLang/docs/SPEC.md#L41-L48) and [`lm/resolve.py`](file://~/LMLang/lm/resolve.py). Built-in `List` and `Opt` take type parameters (`(List a)`), and functions can use single-letter type variables `a`, `b`. However, **user-defined `type` declarations cannot be parameterized** (e.g., you cannot define `(type (Pair a b) (rec (fst a) (snd b)))` or `(type (Result a e) ...)`). Every pair or tree structure must be duplicated per concrete type until tuples/generics land.
3. **Asymmetric Error Handling vs. First-Class Values:**
   Errors in LM (`fail Err ...` / `try ... catch`) are a separate control-flow channel from values, *and* higher-order functions (`list.map`, `list.fold`) forbid failing callbacks (ADR-015). Think about what happens in M8 when you have a list of `"10"`, `"20"`, `"abc"` and want to parse them with `str.to-int` (which `fails ParseError`). You **cannot** write `(list.map xs str.to-int)` because `str.to-int` can fail! You are forced to write manual recursive boilerplate for every fallible collection transformation.
4. **Effectful Functions Are Barred from Having `(example ...)` Clauses:**
   In [`lm/check.py`](file://~/LMLang/lm/check.py#L127-L129): `"examples are only allowed on pure functions in v0"`. And in [`lm/check.py`](file://~/LMLang/lm/check.py#L110): exported functions with `f.eff` are exempted from `E-EXAMPLE-MISSING`. As you move into M8 (real I/O applications), the top-level entry points and orchestrator functions will all have `(eff io.out ...)` or `(eff fs.read ...)`. That means `lm test` won't test them at all, and `lm explain` will show zero examples for the most important functions in a script.
5. **The `Overflow` Contradiction in ADR-026 (M8):**
   ADR-026 states: *"`Overflow` behaves like `DivZero` (implicitly possible on arithmetic, not declared in `fails`)."*
   Wait a second! Look at [`lm/prelude.py`](file://~/LMLang/lm/prelude.py) and [`docs/SPEC.md` Section 7](file://~/LMLang/docs/SPEC.md#L98): `/` and `mod` fail `DivZero` *unless the divisor is a nonzero Int literal*, and if they can fail, **the caller MUST declare `(fails DivZero)`** (checked in `lm/forms.py` / `lm/check.py`). If `+`, `-`, and `*` can fail with `Overflow`, either:
   - Every function doing `(+ a b)` must declare `(fails Overflow)` (which breaks Higher-Order Functions like `(list.fold xs 0 +)` because `+` is no longer total!), **OR**
   - `Overflow` is *unchecked* in `fails` declarations—which violates Goal G3 ("absent `fails` = cannot fail; signatures are complete contracts") and means `+` can still be passed to `list.fold` even though it can fail at runtime! This tension needs to be explicitly resolved in SPEC before M8 starts.
6. **Immutable Linked/Tuple Lists (`cons`) vs. Python Recursion/Tuple Copy Cost:**
   In [`lm/interp.py`](file://~/LMLang/lm/interp.py#L30), lists are Python `tuple`s, and `cons` is `lambda x, xs: (x,) + xs`. Prepending $N$ elements via `cons` in recursion is $O(N^2)$ memory allocation and copying! Meanwhile, `list.nth` is $O(1)$ in Python tuples, but if the M8 Go backend lowers `(List a)` to a Go slice `[]T`, `cons` (`append([]T{x}, xs...)`) will still be $O(N)$ per call ($O(N^2)$ in recursive list builders), whereas if Go lowers `(List a)` to a linked list, `list.nth` becomes $O(N)$!
7. **Contract Evaluation Complexity Explosion:**
   In [`lm/interp.py`](file://~/LMLang/lm/interp.py#L52-L65), `requires` and `ensures` are evaluated on **every call**, including every recursive step. If a recursive function over a list of length $N$ has `(requires (list.all xs ...))` ($O(N)$), the function silently becomes $O(N^2)$ when contracts are enabled (the default in both `lm run` and M8 compiled binaries).
8. **Global Acceptance Namespace & Directory Discovery:**
   `lm accept` loads `tests/accept/*.accept` and requires globally unique scenario names across the entire repo, assuming target modules live in `src/` and `examples/`. Once you have multiple independent scripts or apps in `src/` (as planned in [`docs/EXPERIMENTS.md`](file://~/LMLang/docs/EXPERIMENTS.md)), `lm accept` and `lm check` will load and check *all* of them together, and any module name collision across experiments will trigger `E-DUP-NAME`.

---

#### 4. Suggestions for Improvements (Prioritized Action Plan)

Do not abandon LM for the ADR-011 fallback yet—the core checker and human-oracle design are too good. Instead, make these targeted adjustments (most are < 50 lines of Python):

##### Priority 1: Fix Slice Contract Blindness Immediately (5-Line Fix)
In [`lm/index.py`](file://~/LMLang/lm/index.py#L163), change `_node` when `form == "sig"` so that callee signature blocks **include `requires` and `ensures`** (and optionally the first `example`):
```python
keep = [c for c in f.node.items[2:] if head(c) in ("purpose", "sig", "eff", "fails", "requires", "ensures")]
```
Without `requires` and `ensures`, a signature block is *not* a complete contract, and an agent reading a slice is flying blind on preconditions.

##### Priority 2: Add Batch Operations to `lm edit` (Massive Agent Token Saver)
To prevent an agent from burning 5 conversation turns to make 5 micro-edits, add a `batch` operation (or allow `apply` to accept arbitrary edit ops in JSON, not just diagnostic fixes):
- Example: `python3 -m lm edit batch '[{"op":"add-use","module":"m","use":"list"},{"op":"replace-body","sym":"m.f","expr":"..."}]'`
- Better yet, allow `add-Use` and `add-eff`/`add-fails` to be inferred automatically with an `--auto-contract` flag on `replace-body` / `add-decl`! If an agent writes a body that calls `list.map` and `io.print`, why force a fail-then-fix round trip for `E-USE-MISSING` and `E-EFFECT-UNDECLARED` when `lm edit` can add `(use list)` and `(eff io.out)` in one shot? (Recall from ADR-024: *100% of S4 first-try failures were missing `(use list)`*).

##### Priority 3: Close the Ergonomic S5 Outliers Before or During M8
Two tiny language/stdlib additions will slash token counts on real scripts and bring S5 well under `1.3x`:
1. **Multi-branch conditional (`cond`) or multi-expression bodies:**
   - Look at `10-roman`: 14 nested `(if c a (if c b ...))` forms cause deep indentation wrapping past 100 columns. Either add `(cond (c1 e1) (c2 e2) ... (else en))` OR allow `(do e1 e2 ... en)` for effect sequencing (eliminating dummy `(let ((u (io.print ...))) ...)`).
2. **Stdlib Effectful & Fallible Iterators (or List Destructuring):**
   - Since ADR-015 keeps `Fn` values pure and total, how do you iterate with effects or failures? Either:
     - Add **list patterns in `match`**: `(match xs ((list) base) ((cons h t) ...))` so recursive functions over lists don't have to use index `i`, `list.nth`, and `try/catch OutOfRange` (look at how ugly `13-greet` had to be just to loop over `names`!).
     - Or add a bounded loop form `(for ((x xs)) (init acc e0) body)` which is checked inline by `forms.py` (inheriting the enclosing function's `eff` and `fails` accumulators without needing an `Fn` value!). **A `(for ...)` or `(fold-loop ...)` special form solves ADR-015's higher-order effect/failure restriction completely without complicating the type system!**

##### Priority 4: Resolve the M8 `Overflow` and List Complexity Traps Before Writing the Go Backend
1. **Clarify `Overflow` in SPEC:** Decide whether `Overflow` is an *unchecked runtime trap* (like `E-RECURSION-LIMIT` or a contract violation) or a *catchable `LmFail` error* that bypasses static `E-FAILS-UNDECLARED` checking so `+ - *` can still be passed as pure/total function values to `list.fold`. Document this explicitly in `SPEC.md`.
2. **Fix `cons` / `List` representation in the M8 IR:** Ensure the Go runtime represents `(List a)` in a way where both iteration and building lists don't silently turn into $O(N^2)$ copy loops (or provide `list.from-range` / `list.build` primitives).

##### Priority 5: Project Scoping for `src/` Experiments
Before building multiple scripts in `src/`, allow subdirectories under `src/` (e.g., `src/app1/`, `src/app2/`) with their own `accept` files, or let `lm check/test/accept` scope to a target directory so independent experiments don't pollute each other's module namespace and `accept.lock`.

---

### CITATIONS
- [`AGENTS.md`](file://~/LMLang/AGENTS.md)
- [`PRD.md`](file://~/LMLang/PRD.md)
- [`docs/SPEC.md`](file://~/LMLang/docs/SPEC.md)
- [`docs/ARCHITECTURE.md`](file://~/LMLang/docs/ARCHITECTURE.md)
- [`docs/DECISIONS.md`](file://~/LMLang/docs/DECISIONS.md)
- [`docs/TESTING.md`](file://~/LMLang/docs/TESTING.md)
- [`docs/ROADMAP.md`](file://~/LMLang/docs/ROADMAP.md)
- [`docs/EXPERIMENTS.md`](file://~/LMLang/docs/EXPERIMENTS.md)
- [`docs/EVIDENCE.md`](file://~/LMLang/docs/EVIDENCE.md)
- [`bench/results/summary.md`](file://~/LMLang/bench/results/summary.md)
- [`lm/check.py`](file://~/LMLang/lm/check.py)
- [`lm/index.py`](file://~/LMLang/lm/index.py)
- [`lm/edit.py`](file://~/LMLang/lm/edit.py)
- [`lm/accept.py`](file://~/LMLang/lm/accept.py)
- [`lm/interp.py`](file://~/LMLang/lm/interp.py)
- [`lm/types.py`](file://~/LMLang/lm/types.py)
- [`bench/tasks/10-roman/roman.lm`](file://~/LMLang/bench/tasks/10-roman/roman.lm)
- [`bench/tasks/13-greet/greet.lm`](file://~/LMLang/bench/tasks/13-greet/greet.lm)
