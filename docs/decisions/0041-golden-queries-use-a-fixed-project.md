# ADR-041 Golden queries use a fixed project (2026-10-16)

Golden commands run in an isolated temporary working directory exposing only examples and stdlib. This also scopes symbol-only commands (slice, deps, hash) that have no path arguments, while preserving normal CLI project discovery. Index and explain commands use explicit fixed paths where supported. A regression includes a malformed duplicate module in a candidate project's src directory. Regeneration must leave snapshots unchanged for this tooling change.
