# ADR-014 M0 shape: expressions stay s-expr nodes

Date 2026-10-15. `ast.py` validates and orders module/fn clauses only; expression bodies remain positioned s-expr nodes until M1 needs typed views. Why: formatting needs no expression semantics; avoids designing the typed AST before the checker exists. Also fixed during M0: empty `eff/fails/use/export` clauses are dropped (one canonical form), ints/strings are normalized, width excludes ancestors' closing parens.
