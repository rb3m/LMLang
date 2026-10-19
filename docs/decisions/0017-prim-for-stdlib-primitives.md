# ADR-017 `(prim "name")` for stdlib primitives (M1)

Stdlib functions that need host support have body `(prim "mod.name")`, typed by their `sig`, valid only in modules under `stdlib/`. Why: signatures, examples and docs stay uniform in LM; the interpreter (M2) maps names to Python functions. `str.len` renamed `str.length` (a module function may not reuse the prelude name `len`).
