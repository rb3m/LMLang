# ADR-003 S-expression surface syntax

Why: uniform structure (no precedence, no whitespace rules), trivially parseable, I generate it with very low syntax-error rate, node paths are natural. Rejected: ML-like syntax (precedence/layout ambiguity), APL-like density (tokenizes badly), Python-like (large surface of rarely-used constructs). Revisit: if S4 shows paren-balancing errors dominate failures (then add a bracket-free canonical view, not new semantics).
