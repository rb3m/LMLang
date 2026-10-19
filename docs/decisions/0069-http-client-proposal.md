# ADR-069 Backlog 15: HTTP client: PROPOSED, waiting on owner decisions R1-R5 (2026-10-19)

Status: proposed. Not implemented. The design below is agreed by agents; the risky choices R1-R5 are the owner's (2026-10-18 rule). The HTTP server comes after the client.

Agreed by agents (agy, Codex, Claude):
- One effect `net.http` (R6). GET can leak secrets or trigger server actions too, so a read/write split would give false safety.
- Module `http`: `(request method url headers body) -> Response` with `(rec (status Int) (headers (List (Pair Str Str))) (body Str))`, plus `(fetch url)` for GET (`get` is reserved, ADR-047). Network, TLS, timeout, limit and invalid-argument problems fail `http.HttpError (url Str) (msg Str)`. Non-2xx statuses are ordinary responses. msg is a fixed category (`dns connect timeout tls limit invalid-utf8 invalid-request`) and never echoes credentials.
- Parity: methods uppercased (no CONNECT or TRACE); response header names lowercased and sorted, duplicates kept in arrival order (Go does not keep wire order); strict UTF-8 bodies, binary out of scope; no automatic decompression, cookies or retries; HEAD and empty bodies, chunked and truncated bodies and deadlines pinned by tests.
- Backends: urllib or http.client (interpreter and Python target) and net/http (Go), stdlib only. Tested offline with a loopback server and raw-socket fixtures.

Owner decisions (agents split; Claude's recommendation first):
- R1 TLS and plaintext. Always verify certificates and hostnames with the system store, with no bypass (all agree). Plain `http://`: (a, recommended) allowed only to loopback (localhost, 127.0.0.0/8, ::1), for local services and tests; (b) allowed anywhere (agy: LAN devices); (c) never (Codex).
- R2 Redirects. (a, recommended) not followed: a 3xx comes back as a normal response, so a program never changes destination or forwards credentials without saying so (Codex); (b) follow up to 10, no https->http, drop Authorization across hosts (agy).
- R3 Limits: fixed for v0 (all agree): 8 MiB body, 64 KiB and 100 header fields, 5 s connect, 30 s total including DNS and body, a request-size cap.
- R4 Destinations. (a, recommended) any host once `net.http` is allowed, like `fs` paths (agy): LM programs are the owner's own tools, not servers taking untrusted input, and built binaries have no `--allow` to carry a list; revisit for the server. (b) an explicit allow-list (scheme, host, port), private addresses denied, resolved addresses pinned against DNS rebinding (Codex).
- R5 Proxies. (a, recommended) ignore HTTP_PROXY and friends, so behavior stays the same on every machine and ambient settings cannot redirect traffic (Codex); (b) honor them, for corporate or hosted egress (agy).

Revisit when: the owner decides R1-R5; then implement, and update this ADR to accepted.
