# ADR-007 Deliberate omissions in v0

No floats (money/determinism, avoids numeric semantics), no mutation, no inheritance, no overloading, no implicit conversion, no macros, no concurrency, no FFI. Why: each is a source of action at a distance or ambiguity. Add only with a measured need.
