# Guide migration for ADR-084

Line numbers refer to the guide before ADR-084. Blank lines and headings only organized the original text. Library names, types, signatures, effects and failures are available through `lm index --module M`.

| Old lines | Facts and their new location |
| --- | --- |
| 4–10 | Workflow and approval rules kept in the guide. Module discovery now uses `lm index --stdlib --modules` followed by `lm index --module M`. |
| 12 | The guide explains opt-in. `lm help edit` shows `add-ext`, and the catalog prints the manifest entry. `lm help index` lists the existing `--ext` flag. |
| 15–16 | Helper selection, pinning, trust, review and effect approval stayed in the guide. SHA-256 manifest, pure default, E-DEP-EFFECT restrictions, re-fetch diagnostics and versioned publication moved to `lm help fetch`. |
| 18–39 | Module, function, generic and constant examples and expression rules stayed in the guide. |
| 40 | Prelude, Pair, Map/Set rules and effect vocabulary stayed in the guide. `pair`, `map`, `set`, `opt`, `list`, `str`, `json`, `io`, `time` and `rand` members use their module indexes. Map lookup naming, ordering and last-wins, list indexing proofs and equal lengths, JSON variants, scalar conversion and console behavior are documented in their notes, declarations or function purposes. |
| 41 | `pat` notes cover order, opacity and scalar capture offsets. `pat.compile` purpose covers literal proof discharge. The index lists subject-first signatures. |
| 42 | The Bytes literal stayed in the guide. `bytes` index lists operations and result types. Its notes explain encoded field names, offsets, bounds and failure as None. |
| 43 | Vector literal and List-only `len`/`for` stayed in the guide. `vec` index shows the Vec type and operations, and its notes explain the trie and index proofs. |
| 44 | `env` notes and `env.lookup` purpose explain invalid names. The `env` and `fs` indexes show signatures, effects and failures. |
| 45 | `http` notes cover TLS, loopback, fixed limits, no redirects/proxies and the restriction on network examples. `fetch`, `request` and `request-within` purposes give deadlines. |
| 46 | `lm help serve` covers handler signature, failures, effect permissions and interpreter/compiled modes. The `http` index gives decoder signatures and BadEncoding. |
| 47 | `proc` notes and `run` purpose cover POSIX, absolute executable and exact environment. The index shows signatures and effects, and `lm help test` gives subprocess script syntax. |
| 48 | The `given` example, fake-world defaults and checks stayed in the guide. |
| 49 | Naming and core numbers stayed in the guide. `math` index shows Int bounds. `float` index shows conversions, constants, operations and domains. Float notes cover deterministic accuracy, radians, faults, underflow and sin of binary64 pi. `float.pow` and `float.atan2` purposes state zero cases and domain limits. |
| 51–52 | Exact example comparison and fixed-format output moved to `float` notes. `float.fixed` and `float.round` purposes give digit bounds and rounding rules. |
| 53 | `date` notes cover calendar, range, UTC, durations, constant and clock usage. Its index shows functions, strict parse/print formats and the Opt return types. |
| 55–72 | Scenario example, expectations, effect permissions and approval stayed in the guide. |
