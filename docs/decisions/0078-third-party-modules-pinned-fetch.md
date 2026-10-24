# ADR-078 Third-party modules: hash-pinned sources, explicit fetch (2026-10-24, agent consensus)

Status: accepted (2026-10-24). Owner approved the minimal v1 below ("add it to the backlog and send to codex"); backlog 27. Amended by ADR-079: externals use only stdlib (the pinned transitive closure below is superseded) and pins carry effect allowances.

Context: modules are found by file stem in CLI paths, src/, examples/ and stdlib/ (one global namespace, E-DUP-NAME on collision). There is no way to name an outside module's source or version. Owner's idea: `use` itself says where to get a module and which version, so the AI is its own package manager.

Agreed by agents (agy, Codex, Claude):
- Declare once per project, not in every `use`: one dedicated dependency declaration (not the entry module, since a project can have several entries and tests) maps each external stem to a source URL and full SHA-256. Ordinary modules keep `(use geo)`. Why: repeating URLs and hashes costs tokens and multiplies conflict and update sites; an upgrade is one edit. It is a small manifest written in LM syntax, and says so.
- The hash is the pin. Version strings are at most labels; no ranges, no semver resolution, fetch never picks a version.
- `lm check`, `lm test` and `lm build` never touch the network. A new `lm fetch` downloads into a hash-keyed cache and verifies bytes; an unfetched or mismatched pin is a diagnostic with a fetch fix op. Fetch runs no dependency code and bounds download size.
- v1 sources are direct HTTPS file URLs only (no registries, git repos or archives; a repo URL and tag do not identify a file).
- The declaration pins the complete transitive closure. Missing pins fail; one stem with two hashes (diamond) is an error.
- Cached modules are never ambient: only pinned stems load, local files cannot shadow them, and cache placement never grants stdlib `prim` privileges.
- Interpreter, Go and Python targets consume the same verified closure. A hash proves identity, not trust: choosing a pin still needs review.

Split, settled 2-1:
- Hash unit: one module file (Codex, Claude) vs package tree hash (agy). Module files for v1: matches LM's existing per-module identity and avoids package membership and tree-hashing rules; a multi-module library pins each file. Revisit if coherent multi-module releases become common. Hash exact UTF-8 file bytes (Codex), not canonical text, which would need its own versioned algorithm.
- Collisions: keep ADR-047 rename (Codex, Claude, who first proposed aliases) vs local aliases `(use (gjson json ..))` (agy: authors cannot control third-party stems). Rename wins: aliases are an exception to an owner rule and loosen ADR-005's qualifier-equals-module identity. A conflicting dependency is renamed with its references, then pinned as the adapted copy.
- Effect summary at fetch (agy: keep; Codex: later, computed from the checked closure as review information, not authorization). Deferred to after v1.

Cut from v1: aliases, version labels, repo/archive sources, canonical hashing, automatic resolution, fetch-time effect summaries.
Implemented (2026-10-24): project-root `lm.deps` uses `(deps (pin STEM "HTTPS-URL" "SHA256") ...)`, rewritten canonically with one pin per line sorted by stem. SHA-256 covers exact file bytes. `$LM_CACHE` defaults to `~/.cache/lm`; entries are `<hash>/<stem>.lm`. E-DEPS diagnoses invalid declarations; E-DEP-UNFETCHED and E-DEP-HASH point to pins with a fetch fix, E-DUP-NAME rejects search-path/stdlib collisions, and E-DEP-UNPINNED points to external uses outside the complete pinned/stdlib closure. Verified externals remain non-target and non-stdlib, so `prim` is rejected. `fetch` uses an injectable byte downloader, verified HTTPS/TLS, no redirects, status 200 only, an 8 MiB limit and atomic cache writes after verification; it never parses/checks/runs downloads. Plain fetch emits per-pin JSON statuses and exits 0/1; `--pin STEM URL` is the explicit trust moment, computes the hash, replaces/adds the sorted declaration and prints the pin line. All interpreter and build targets share the offline loader. Offline export/import remains deferred; copying the declaration and matching cache entries suffices for v1.
