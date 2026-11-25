# ADR-082 Backlog 31: per-call HTTP deadline `http.request-within` (2026-11-25, agent consensus)

Status: accepted (2026-11-25). Owner handed the decision to the agents. Amends ADR-069 R3 (the total deadline is no longer fixed for every call); all other R3 limits stand.

Context: ADR-069 R3 fixed the client limits for v0: 5 s connect and a 30 s total deadline covering DNS, connect, TLS, writes, headers and the whole body. The owner's `local-llm` helper (a local Ollama model) needs 10-14 s for a cold load and about 52 s for 1,400 tokens on an M4 with 16 GB, so it preloads in a separate call and caps replies at about 600 tokens. Responses are not streamed, so an idle timeout would not help. Measurements: Vault, `SoftwareDevelopment/AI/20261125-0510 LMLang HTTP Deadline and Local LLM Jobs.md`.

Options: (1) raise the fixed default (e.g. 120 s); (2) a per-call total deadline as a new fn; (3) an idle/read timeout instead of or as well as the total; (4) separate connect, first-byte and total limits in an options record.

Decision (Claude, Codex, agy agree on 2):
- New fn `(http.request-within method url headers body secs) -> Response`, effect `net.http`, fails `http.HttpError`. `secs` is the total deadline in whole seconds, valid 1..600 inclusive; anything else fails `invalid-request` before any network I/O.
- `request` and `fetch` keep 30 s; `request` is a thin wrapper passing 30. Connect stays min(5 s, remaining total). Every other ADR-069 rule (limits, categories, TLS, redirects, proxies) is unchanged.
- One monotonic deadline from the start of the call; expiry in any phase (DNS, connect, TLS, write, headers, body) is `timeout`, identically in the interpreter, Go and Python targets.
- Why: (1) makes every hung call wait longer and one number never fits; (3) bounds nothing without streaming and does not cover a slow first byte; (4) spends tokens and test surface on knobs nobody needs yet. A positional Int keeps calls short (no record type to build); seconds avoid false precision and flaky sub-second parity tests; the 600 s cap keeps every call bounded. `request-within` reads as a total deadline; `request-timed` sounds like it reports elapsed time (agy).
- Tests (Codex, agy): 0, -1 and 601 fail `invalid-request` with no I/O; 1 and 600 accepted without waiting out the cap; a drip-fed body that keeps each read short but exceeds the budget times out in all three runtimes.

Revisit when: streaming responses exist (add an idle timeout then), or a program needs more than 600 s or separate first-byte limits.

Implemented (2026-11-25, v0.13.0): one prim `http.request-within` in the interpreter, Python and Go targets; `request` wraps it with 30. Tests use `request-within ... 1` for the slow, slow-body and drip endpoints in all three runtimes, replacing the old test-only source patches of the 30 s constant. Verified by Claude: full unit suite with loopback sockets (410 tests, none skipped), and live against Ollama: a cold gemma4:e4b load (11.7 s) plus 1,500 tokens in one call, 65.7 s, interpreter and the Go-built `local-llm` helper. Implementation by Codex (gpt-6.2-sol, medium effort).
