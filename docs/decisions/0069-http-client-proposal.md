# ADR-069 Backlog 15: HTTP client (2026-10-19, agent consensus; owner decided R1-R5)

Status: accepted (2026-10-19). The owner took every recommended option: R1a (plain `http://` only to loopback), R2a (redirects not followed), R3 fixed limits, R4a (any host once `net.http` is allowed), R5a (proxy variables ignored). The HTTP server comes after the client.

Agreed by agents (agy, Codex, Claude):
- One effect `net.http` (R6). GET can leak secrets or trigger server actions too, so a read/write split would give false safety.
- Module `http`: `(request method url headers body) -> Response` with `(rec (status Int) (headers (List (Pair Str Str))) (body Str))`, plus `(fetch url)` for GET (`get` is reserved, ADR-047). Network, TLS, timeout, limit and invalid-argument problems fail `http.HttpError (url Str) (msg Str)`. Non-2xx statuses are ordinary responses. msg is a fixed category (`dns connect timeout tls limit invalid-utf8 invalid-request`) and never echoes credentials.
- Parity: methods uppercased (no CONNECT or TRACE); response header names lowercased and sorted, duplicates kept in arrival order (Go does not keep wire order); strict UTF-8 bodies, binary out of scope; no automatic decompression, cookies or retries; HEAD and empty bodies, chunked and truncated bodies and deadlines pinned by tests.
- Backends: urllib or http.client (interpreter and Python target) and net/http (Go), stdlib only. Tested offline with a loopback server and raw-socket fixtures.

Owner decisions (agents split; Claude's recommendation first; the owner chose each (a)/recommended option):
- R1 TLS and plaintext. Always verify certificates and hostnames with the system store, with no bypass (all agree). Plain `http://`: (a, recommended) allowed only to loopback (localhost, 127.0.0.0/8, ::1), for local services and tests; (b) allowed anywhere (agy: LAN devices); (c) never (Codex).
- R2 Redirects. (a, recommended) not followed: a 3xx comes back as a normal response, so a program never changes destination or forwards credentials without saying so (Codex); (b) follow up to 10, no https->http, drop Authorization across hosts (agy).
- R3 Limits: fixed for v0 (all agree): 8 MiB body, 64 KiB and 100 header fields, 5 s connect, 30 s total including DNS and body, a request-size cap.
- R4 Destinations. (a, recommended) any host once `net.http` is allowed, like `fs` paths (agy): LM programs are the owner's own tools, not servers taking untrusted input, and built binaries have no `--allow` to carry a list; revisit for the server. (b) an explicit allow-list (scheme, host, port), private addresses denied, resolved addresses pinned against DNS rebinding (Codex).
- R5 Proxies. (a, recommended) ignore HTTP_PROXY and friends, so behavior stays the same on every machine and ambient settings cannot redirect traffic (Codex); (b) honor them, for corporate or hosted egress (agy).

Revisit when: the HTTP server is designed (R4 destinations and limits get revisited then).

Implemented (2026-10-19, v0.7.0): module `http` and effect `net.http` in the interpreter, Go and Python targets, with fixed-category errors and system trust roots only (SSL_CERT_FILE/SSL_CERT_DIR and proxy variables ignored). Effect mocking now fails closed: an effectful prim the fake world does not route is denied, and an example on a fn declaring `net.http` is E-EXAMPLE. Verified by Claude: loopback suites (Codex's sandbox could not bind sockets), and live probes in all three runtimes with hostile HTTPS_PROXY and SSL_CERT_FILE set gave identical results: 200, 301 not followed, `tls` for expired, wrong-host and self-signed certificates, `invalid-request` for public `http://`, `127.1`, userinfo and `ftp://`, `dns` for `.invalid`. Implementation by Codex (gpt-6.1-sol, high effort).
