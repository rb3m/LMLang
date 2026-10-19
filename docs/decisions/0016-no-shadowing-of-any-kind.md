# ADR-016 No shadowing of any kind (M1)

Locals cannot reuse reserved words, prelude names, module functions, or bindings in scope. Why: "a name has exactly one referent" is what lets a slice be understood without scope reasoning. Cost: slightly more name invention.
