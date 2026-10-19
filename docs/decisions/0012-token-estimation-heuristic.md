# ADR-012 Token estimation heuristic

Until a real tokenizer is available offline: tokens ~= count of regex `\w+|[^\w\s]` matches (word pieces + punctuation), applied identically to LM and Python. Ratios matter, absolutes do not. Revisit: if a tokenizer library can be used without breaking R-Q1 (optional dev-only dependency is acceptable).
