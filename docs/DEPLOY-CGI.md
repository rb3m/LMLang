# Deploy an LM handler as CGI

Write a named handler with `(sig (req http.Request) -> http.Response)` and handle
all declared failures inside it. Ordinary Request examples can test its behavior.
Build a standalone Python program:

```sh
bin/lm build --target py --serve web.handle -o web.py
```

Copy the built `web.py` to the site's CGI-enabled directory as `web.cgi`. Keep the
first-line shebang (`#!/usr/bin/env python3`), or set it to the hosting account's
absolute Python >= 3.10 interpreter path if required. Use Unix line endings and
make the script executable:

```sh
chmod 755 web.cgi
```

Configure the web server's CGI mapping according to the hosting control panel.
DreamHost-style CGI starts one process per request. The CGI environment must
include the raw `REQUEST_URI`; absent URI returns an empty 500. QUERY_STRING,
REQUEST_METHOD, CONTENT_LENGTH, CONTENT_TYPE and HTTP_* provide the other request
fields. Stdin supplies the strict UTF-8 body, limited to 8 MiB. Responses and
headers are validated before output; JSON fault diagnostics go to the site's CGI
stderr/error log. The script needs no repository checkout or third-party package.

The built program grants its handler's declared effects and runs with the hosting
account's authority. HTTPS terminates at the hosting web server. A local smoke
test, before uploading, can invoke CGI directly:

```sh
REQUEST_METHOD=GET REQUEST_URI='/hello?name=LM' QUERY_STRING='name=LM' ./web.cgi
```

For local listener testing, run `./web.cgi --listen --port 8080`; the default bind
is 127.0.0.1. Another loopback port can be chosen with `--port`; `--port 0` selects
a free port and prints the actual address on stderr. A non-loopback `--host`
requires `--public`. The listener has no TLS and serves one request at a time;
a slow client can occupy it for up to 30 seconds.
