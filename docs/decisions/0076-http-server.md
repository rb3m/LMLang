# ADR-076 Backlog 15: minimal HTTP server, CGI and loopback listener (2026-10-19, agent consensus)

Context: backlog 15 asks for a minimal HTTP server so the Python target can serve on DreamHost. Round 1 assumed WSGI under Passenger. Codex pointed out, and Claude confirmed on help.dreamhost.com ("Supported and unsupported technologies"), that DreamHost no longer supports Passenger, while CGI is supported on all servers. Fn values must be pure and total, so an effectful handler cannot be a lambda.

Decision:
1. Shape. A handler is a named fn `(sig (req http.Request) -> http.Response)` with any effects it needs, selected at build or run time. There is no new effect and no LM-level serve loop. A handler that declares `fails` is E-SERVE at check time: every failure must be handled.
2. Adapters in v0 (WSGI deferred):
   - CGI: `lm build --target py|go --serve mod.handle` emits a CGI program that handles one request per process. Our own code reads the CGI variables and stdin, so the runtimes agree on identical CGI input.
   - Loopback listener: `lm serve mod.handle [--port N] [--public] [--allow EFF]..` (interpreter) and `--listen` mode for built programs. Both use our own HTTP/1.1 parser in Python and Go. Requests are handled one at a time with `Connection: close`.
   - Built programs grant their declared effects (as all built binaries do). `lm serve` needs `--allow` like `lm run`.
3. Binding. Listeners default to 127.0.0.1:8080. Any other address needs `--public`, for built listeners too. There is no TLS: a reverse proxy, or the web server in CGI mode, terminates it.
4. Request `(rec (method Str) (target Str) (query Str) (headers (List (Pair Str Str))) (body Str))`.
   - Method: kept exactly as received; it must be a token.
   - Target: origin form only (starts with "/"), raw with percent-encoding kept, query removed. Other forms get 400.
   - Query: raw, without "?".
   - Headers: names lowercased, values with surrounding whitespace trimmed.
   - Body: strict UTF-8. Invalid UTF-8 in the target, query or body gets 400 before the handler runs.
   - Adapter guarantees differ. The listener keeps header order and duplicates. CGI cannot (HTTP_* variables are merged by the web server), so its headers are sorted by name. In CGI the target comes from REQUEST_URI, which is required; without it the response is 500.
5. Helpers.
   - `http.url-decode s` fails `http.BadEncoding` on a malformed % escape or invalid UTF-8. `+` stays `+`.
   - `http.query-pairs q -> (List (Pair Str Str))` splits on `&`, skips empty fields, treats a field without `=` as an empty value, decodes `+` as a space and then percent-decodes, keeps duplicates in order, and fails BadEncoding.
6. Response validation, before any byte is written; a violation gets an empty 500:
   - Status must be 200-599.
   - Header names must be RFC 9110 tokens. Values are visible ASCII, space and tab only.
   - The handler may not set framing headers (`content-length transfer-encoding connection keep-alive upgrade te trailer`, compared case-insensitively). We frame with Content-Length.
   - 204, 205 and 304 must have an empty body. HEAD gets the GET headers with Content-Length and no body.
   - A fault or contract violation gives 500 with an empty body. The diagnostic JSON goes to stderr only, and stdout carries only the protocol.
7. Listener profile and limits:
   - Request line plus headers at most 64 KiB (431) and at most 100 headers (431). Body at most 8 MiB (413), Content-Length framing only.
   - Malformed framing:
     - Any Transfer-Encoding: 501.
     - Transfer-Encoding together with Content-Length: 400.
     - Duplicate, conflicting or invalid Content-Length: 400.
   - Versions and methods:
     - HTTP/1.0 and 1.1 only; anything else gets 505.
     - CONNECT gets 501.
     - `Expect: 100-continue` gets an interim 100 before the body is read.
   - Deadlines: 10 s to receive the headers, 30 s for the whole request (408).
   - The listener produces all of these responses without calling the handler.
   - Transport bytes are identical between the Python and Go listeners. CGI framing (`Status:` header) is identical between the CGI targets.
8. Testing:
   - Handler examples are ordinary examples with Request values.
   - CGI: environment-plus-stdin fixtures run on all targets.
   - Listener: loopback raw-socket tests for each limit and rejection code, HEAD, Unicode, duplicate headers and recovery after a fault.

Owner-facing security points (defaults are the conservative ones): a CGI handler is reachable by anyone who can reach the web server and runs with its declared effects. `--public` exposes a listener beyond the machine. Requests are handled one at a time, so one slow client delays the others for up to 30 s.

Who agreed: round 1, agy and Codex both chose a named handler selected at build or run time, no new effect, loopback default, one request at a time, 64 KiB/100 headers, 8 MiB body and a generic 500. Codex flagged that Passenger is unsupported on DreamHost. Round 2, agy agreed to all tie-breaks T1-T6 as proposed. Codex agreed to T2, T3 and T5 and asked for the refinements adopted in rules 4-7: adapter-specific CGI guarantees with a required raw-URI source, method case kept, origin-form targets, defined query-helper behavior, a control-character ban, case-insensitive framing names, 204/205/304/HEAD rules, and a restricted framing profile with fixed rejection codes instead of chunked decoding.

Implementation note (v0.11.0): CGI `QUERY_STRING` is authoritative, even when REQUEST_URI carries a different query, and an absent QUERY_STRING is empty. The 64 KiB header limit includes the request line and the terminating blank line. Duplicate Content-Length is rejected even when the values match. Reason phrases follow Go's labels in all runtimes.

Verification: Claude ran the full gate with loopback binding allowed (363 unit tests including the raw-socket listener suites, check, test, accept --guard, the three bench projects, export scan). A probe handler served 20 raw requests through the interpreter (`lm serve`), Go and Python listeners with byte-identical responses: query decoding, a strict UTF-8 body, duplicate headers in order, HEAD, Expect 100, rejection codes 400/413/431/501/505, and an empty 500 for a framing header, a 204 with a body and a contract fault, with the next request still served. The same handler in CGI mode gave identical bytes in all three runtimes, including sorted headers and a 500 without REQUEST_URI. A non-loopback `--host` without `--public` exits 2 in all three, and handlers with the wrong signature or declared fails are E-SERVE. Implementation by Codex (gpt-6.1-sol, high effort), resumed once after a usage limit.
