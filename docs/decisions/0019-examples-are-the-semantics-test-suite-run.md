# ADR-019 Examples are the semantics test suite; run args are LM expressions (M2)

`tests/spec/run/semantics.lm` pins the runtime semantics (floor division, lazy `and`/`or`, nested patterns, closures, try/catch...) as examples in LM itself, executed by `lm test`. `lm run` takes LM expressions as arguments so constructors and lists need no second argument syntax, and reuses the checker for argument typing. Why: one notation for code, tests and invocation; fewer tokens than JSON plumbing.
