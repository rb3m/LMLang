# ADR-081 Backlog 29: database access deferred; when built, a pure stdlib `db` interface plus driver modules (2026-10-28, agent consensus)

Status: accepted as a deferral (2026-10-28). Owner asked whether database support is worth having, given the workarounds, and if so preferred a separate module with a pluggable interface over a core feature.

Context: LM has no database support. Programs can already reach one with `proc.run` (the `sqlite3` CLI with `-json`, parsed by `json`), with `http.request` (PostgREST, CouchDB, Turso and similar), or keep data in files with `fs` and `json`. Every backend is stdlib only (ADR-002, generated `go.mod` has no requires). Python ships `sqlite3`, but Go's `database/sql` has no driver, so a native SQLite prim needs cgo or a large dependency and breaks three-backend parity. Function values are pure and total (SPEC section 12), so an interface cannot be a record of effectful functions. Externals cannot use `prim`, may `use` only stdlib, and cannot be allowed `proc.run` (ADR-079).

Options: (1) build now: a stdlib `db` module with SQLite prims; (2) build now: a pure-LM interface with driver modules over `proc.run` and `net.http`; (3) defer until a real program needs it, and fix the shape now so that work starts from (2).

Decision (agy, Codex, Claude agree on 3):
- Defer. Workarounds cover today's needs, and an interface designed before a real workload would guess at transactions, NULLs, numeric limits and errors. Trigger: a daily-use program (backlog 21) or an experiment hits a wall with the workarounds; record that evidence in backlog 29.
- No native database prims while backends are stdlib only (all three).
- Shape when built:
  - A pure stdlib module `db` holds only the shared types: `Val` (sum: `Null`, `Int`, `Float`, `Str`, `Blob` with an explicit encoding), `Rows` (ordered column names plus `(List (List Val))`), `DbError`, and checked decoders from rows into application records. It lives in stdlib because third-party drivers may import only stdlib.
  - Drivers are separate modules that expose the same function names and signatures, `query(sql, params) -> Rows` and `execute(sql, params) -> Int`. Plugging in a different database means changing the module qualifier. A sum-typed `Driver` with explicit dispatch waits until two drivers prove a common contract; that dispatcher declares the union of its drivers' effects.
  - Parameters are always bound separately from the SQL text, never interpolated. HTTP drivers use the service's structured parameter protocol. A `sqlite3` CLI driver ships only after a binding mechanism is shown safe (the CLI's argv and `-json` do not bind parameters); otherwise that driver stays deferred.
  - Drivers declare the effects they really use (`proc.run`, `net.http`). No `db.read`/`db.write` effects.
  - The SQLite CLI driver is first-party (in this repo) or project-local, since `proc.run` is not allowed in pins. HTTP drivers may be third-party pins with `(allow net.http)`.
- Before calling drivers interchangeable: one concrete workload and conformance cases that pass on the interpreter, Go and Python targets.

Split, settled 2-1:
- Effects: hide the transport behind `db.read`/`db.write` (agy) vs keep the real `proc.run`/`net.http` (Codex, Claude). Real effects win: an SQL statement can do more than its name suggests, and hiding a subprocess under a database effect weakens the effect system that callers and ADR-079 allowances rely on.
- Rows: `(List (Map Str Val))` (agy) vs column names plus value lists (Codex, Claude). Lists win: they keep column order and duplicate names, and the decoders give records by name.
- SQLite driver location: stdlib (agy) vs project-local first, stdlib later (Codex). Settled as first-party or project-local, decided when the driver is built.
- agy's record-of-closures interface was dropped because function values must be pure (SPEC section 12); agy's `Val` sum type was kept.

Biggest risk (both reviewers): promising interchangeable semantics. A process-per-call `sqlite3` driver has no connection, so it cannot hold a transaction open across calls; `BEGIN..COMMIT` must go in a single statement batch, and the interface must not suggest otherwise.

Revisit when: a program needs a database (the trigger above), Go gains a stdlib SQL driver, or the stdlib-only rule changes.
