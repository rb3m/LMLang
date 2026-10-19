# Architecture — reference implementation

Python >= 3.10, stdlib only (ADR-002). Goal: small, readable-by-agent modules, each < ~400 lines, each phase returns diagnostics instead of raising.

## Layout

```
lm/
  __init__.py, __main__.py  package marker and `python3 -m lm` entry (calls cli.py)
  sexpr.py     reader: text -> positioned s-expr nodes (line, col, path)
  ast.py       module/fn shape validation + canonical clause ordering (M0). Expressions stay s-expr nodes; typed views and node path ids arrive in M1
  printer.py   canonical text (single source of truth for formatting) + format_text()
  diag.py      Diagnostic dataclass, codes table, JSON emit
  program.py   shared model: ModInfo, FnInfo, TypeInfo, ErrInfo, VariantInfo, Program (modules, refs, calls, diags)
  loader.py    find modules (src/, examples/, stdlib/, given paths), parse, canonicalize, link `use`, detect cycles
  prelude.py   closed prelude tables, reserved words, effect set
  types.py     type tuples + Subst (unification with metas; generics via inst())
  resolve.py   Resolver: symbol tables, name lookup + diagnostics, type expressions, fn signatures
  check.py     Checker(CollFormsMixin, FormsMixin, Resolver): per-fn checking, contracts, examples, calls, effects/fails accumulation
  forms.py     special forms: if let let? match lam list new get with and or fail try note prim
  forms_coll.py special forms mapof/setof (constant keys, duplicates) (ADR-049)
  index.py     Index over prog.refs: norm/find symbols, index lines, callers, deps, slice (collect/closure/budget), hash; `tokens()` heuristic
  bench.py     `lm bench`: case equivalence LM vs Python, S1-S6, mutation suite; data in bench/tasks, output in bench/results
  explain.py   plain-language function description (sig, fails with fields, effects, contracts, examples, callers)
  accept.py    scenario parsing, digest, lock read/write, guard, execution (type-checks args/expected, captures io.out)
  edit.py      path addressing (locate/get_at/set_at over canonical trees), Work set, ops table, fix application; rename walks prog.refs
  values.py    runtime values (Var, Rec, Closure...), LM-syntax `show()`
  tree.py      Map/Set values: persistent AVL tree + `Coll` (ADR-049/050; Go twin runtime/go/coll.go)
  prims.py     Python implementations of stdlib `(prim "..")` bodies (PRIMS table); siblings by family: float_prims.py (Float),
               str_prims.py (strings), io_prims.py (I/O), rand_prims.py (clock/random, SplitMix64), json_prims.py (JSON), coll_prims.py (map/set)
  interp.py    Interp: tree-walking evaluator, contracts, capability gating, checked 64-bit arithmetic, frame stack
  tailcall.py  shared source-level self tail-call sites + interpreter loop-transfer value (ADR-051 item 1)
  runtime_cases.py effectful runtime fixtures NAME.cases.json (ADR-051; docs/TESTING.md)
  runner.py    test_program (examples), runtime_diag, in_big_stack (512MB thread stack for deep recursion), FAULT_CODES
  fault.py     E-OVERFLOW/E-FLOAT diagnostic from the Interp frame stack: frames, node path, `lm run` replay
  commands.py command registry and generated usage
  cli_help.py  help and bundled guide commands
  guide.md     agent syntax, workflow and stdlib guide
  cli.py       command dispatch and toolchain exception boundary
  cli_common.py shared flags, loading and diagnostic reporting
  cli_project.py fmt/check/test/bench commands
  cli_new.py   `lm new` project scaffold (ADR-048)
  cli_query.py index/slice/callers/deps/hash/explain commands
  cli_edit.py  edit operation CLI
  cli_run.py   function runner CLI
  cli_accept.py acceptance scenario CLI
  ir.py        target-neutral IR (expression tree, LM names unmangled) + free_locals (ADR-035)
  lower.py     checked Program -> IR for the fns reachable from roots; lower_examples() for the differential harness
  gobackend.py GoGen core: linearization (spills keep left-to-right order), functions, contracts, headers, emit_main/emit_cases
  gobackend_expr.py GoExprMixin: expression emitters and pattern helpers
  gobackend_names.py shared Go name mangling and string literals
  pybackend.py PyGen core: linear code emitter, function generation, contract wrappers, emit_main/emit_cases (ADR-062)
  pybackend_expr.py PyExprMixin: expression emitters, pattern matching, loop lowering
  pybackend_embed.py mechanical embedding and reachability filtering of runtime sources (tree, float math, coll/rand/json/io prims)
  pybackend_names.py shared Python name mangling and literal formatting
  build.py     `lm build`: target dispatch (`go` or `py`), entry check (ADR-031), write sources, invoke compiler/set executable; run_examples_go(), run_examples_py()
  runtime/go/  Go runtime copied next to the generated main.go: value.go (values, equality, show),
               rt.go (fail/fault, checked Int ops, calls, stdout, entry/harness), prims.go (ONE func per prim; prims_text.go: M10 str prims),
               float.go (checked Float ops without FMA, canonical text = Python repr, Float prims),
               coll.go (Map/Set AVL tree, mapOf/setOf, map/set prims), rand.go (clock/random), json.go (JSON)
  runtime/py/  Python runtime embedded into standalone Python build outputs: rt.py (values, checked Int/Float ops, calls, depth accounting, prims), entry.py (CLI entry/runner, diagnostics, seed)
stdlib/        list.lm pair.lm str.lm opt.lm map.lm set.lm math.lm float.lm io.lm fs.lm time.lm rand.lm json.lm (LM source over lm/prims.py primitives)
src/           user programs
examples/      sample projects used by tests and bench
games/         standalone LM projects (run ../../bin/lm inside; e.g. games/roadster-lander)
tests/
  unit/        unittest modules per lm/*.py
  spec/        one fixture per SPEC rule and per diagnostic code
  accept/      *.accept scenarios (human oracle)
  golden/      expected outputs for index/slice/deps/hash/explain
bench/         tasks/NN-name/ (name.lm, name.py, cases.json), results/ (summary.md, results.json generated by `lm bench`; s4-attempt1.json is frozen evidence)
bin/lm         `lm` command wrapper (ADR-048)
accept.lock    digests of human-approved scenarios (repo root)
```

## Pipeline

```
text --sexpr--> nodes --ast--> Module --loader--> Program(graph)
   --resolve--> --types--> --effects--> diagnostics[]
                                   \--> interp (only if no errors)
                                   \--> lower -> IR -> gobackend -> Go source -> `go build` (lm build --target go)
                                                   \-> pybackend -> Python script (lm build --target py)
```
Entry points: `sexpr` (Atom kinds int|str|sym|type; SList) -> `ast.canonicalize()` (shape + clause order) -> `loader.load(paths)` builds `Program` -> `Checker(prog).run()`. Full checking rule list: docs/SPEC.md section 12.

`Program` is the shared object: `modules`, `symbols` (qualified name -> decl), `refs` (node path -> target), `calls` (caller -> callees). Query commands (`slice`, `callers`, `deps`) read only `Program`; they never re-parse.

## Key mechanisms

- **Node paths**: `module/fn/clause/idx/idx...`; assigned at parse, stable under formatting, used by diagnostics and edit ops.
- **Slice**: given symbol S: S's full text + for each direct reference its signature block (`purpose sig eff fails requires ensures`, ADR-028) + referenced type declarations in full. `--bodies` adds callee bodies; `--depth N` follows transitively. Correctness argument: with qualified-only names, exact resolution, and declared effects/fails, nothing outside the slice can change what S's text means. `--budget N` truncates by dropping the deepest signatures first and says so.
- **Edit ops**: parse op args as s-expr, apply to the AST, reprint canonical, run check on touched modules, print diff-size and diagnostics. Never emit the whole file.
- **Effects/fails**: accumulated during checking from each callee's *declared* signature, so check order never matters and recursion needs no fixpoint (ADR-018; see Error handling policy).
- **Faults vs failures**: LM failures are `LmFail` (catchable by `try`, declared in `fails`); faults (Overflow, Violation, RecursionError) are other Python exceptions that `try` never catches. Interp frames are popped only on normal return (and truncated by `try` on a caught failure), so after a fault they still describe where it happened.
- **Capability gating**: interpreter holds an `allowed` set; prims with effects check it.
- **Contracts**: `requires` evaluated before body with params bound; `ensures` after with `result` bound.
- **Self tail calls**: `tailcall.tail_sites` walks only the permitted body positions; the interpreter and lowering share the same node-identity decisions. `Interp.call_fn` consumes `TailArgs` in a loop with fresh environments and one frame. Lowering emits `ir.TailCall`; Go uses next-argument slots and fresh locals inside a loop. With contracts on and postconditions present, both keep argument histories on the heap and check them innermost first on exit; otherwise no history is allocated. Calls inside `try`, lambdas, contracts and examples are excluded.
- **Determinism**: all listings sorted; no timestamps in outputs except `bench/results`.

- **Native and script builds** (ADR-026/032/033/062): the interpreter is the oracle. `lower.py` makes every runtime decision of `interp.py` explicit (call kinds, captures, match tests, fail/try, contracts with sites); a backend is a printer plus a runtime. `gobackend` targets Go (`Value = any`, fail as panic caught by try's deferred recover, faults as panics caught by entry); `pybackend` targets Python (emits a standalone self-contained script with embedded runtime `lm/runtime/py/rt.py`). Both count LM call depth so runaway recursion is a fault (E-RECURSION-LIMIT) instead of an uncontrolled host stack crash.
- **Adding a prim**: Python in `lm/prims.py` (PRIMS table), Go in `lm/runtime/go/prims.go` (`func prim_<name>(args Value..) Value`, `.`/`-` -> `_`), and Python backend runtime in `lm/runtime/py/rt.py` (`prim_<name>(*args)`); `tests/unit/test_gobackend.py` fails if the Go twin is missing.

## Error handling policy

Effects/fails are accumulated during checking (not a separate pass): `Checker.effs` and a stack of `frames` (one per active `try`); `sandbox()` isolates lambdas, contracts and examples. Callee effects/fails come from the callee's *declared* signature, so check order never matters.

Phases never raise on user-program faults; they append `Diagnostic`. Exceptions inside `lm/` mean a bug in the toolchain and exit code 2 with a traceback. Exit codes: 0 ok, 1 diagnostics with errors, 2 toolchain bug, 3 usage error.

## Future (not in v0)

Content-addressed store (`.lm/store`, hash -> AST) with text as a rendered view; a Python backend over the M8 IR for the server (ADR-027); `lm serve` (JSON-RPC, keeps Program in memory); effect mocking in examples; alpha-normalized hashes.
