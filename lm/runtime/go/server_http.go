// Shared server request values, CGI input and validated response framing (ADR-076).
package main

import (
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"sort"
	"strconv"
	"strings"
	"unicode/utf8"
)

var httpRequestType = &RecType{"http.Request", []string{"method", "target", "query", "headers", "body"}}

func prim_http_url_decode(s Value) Value {
	raw := s.(string)
	decoded, err := url.PathUnescape(raw)
	if err != nil || !utf8.ValidString(decoded) {
		return lmFail("http.BadEncoding", raw)
	}
	return decoded
}

func serverDiagnostic(msg string) {
	printFault(&Fault{Diag{Code: "E-SERVE", Severity: "error", Msg: msg, Fix: []any{}}})
}

func serverTarget(raw string) (string, bool) {
	if !strings.HasPrefix(raw, "/") || !utf8.ValidString(raw) || strings.Contains(raw, "#") {
		return "", false
	}
	for _, c := range raw {
		if c <= 32 || c == 127 {
			return "", false
		}
	}
	target, _, _ := strings.Cut(raw, "?")
	return target, true
}

func serverHeaderValue(s string, response bool) bool {
	for _, c := range s {
		if c < 32 && c != '\t' || c == 127 || response && c > 126 {
			return false
		}
	}
	return true
}

func serverLength(s string) (int64, int) {
	if s == "" {
		return 0, 400
	}
	for _, c := range s {
		if c < '0' || c > '9' {
			return 0, 400
		}
	}
	digits := strings.TrimLeft(s, "0")
	if digits == "" {
		digits = "0"
	}
	n, err := strconv.ParseUint(digits, 10, 64)
	if err != nil || n > httpBodyLimit {
		return 0, 413
	}
	return int64(n), 0
}

func serverBody(r io.Reader, size int64) (string, int) {
	body := make([]byte, int(size))
	if _, err := io.ReadFull(r, body); err != nil {
		if e, ok := err.(interface{ Timeout() bool }); ok && e.Timeout() {
			return "", 408
		}
		return "", 400
	}
	if !utf8.Valid(body) {
		return "", 400
	}
	return string(body), 0
}

func serverCGIRequest(env map[string]string, r io.Reader) (Value, int) {
	raw, present := env["REQUEST_URI"]
	if !present {
		return nil, 500
	}
	target, valid := serverTarget(raw)
	method, query := env["REQUEST_METHOD"], env["QUERY_STRING"]
	if !valid || !httpToken(method) || !utf8.ValidString(query) {
		return nil, 400
	}
	var length int64
	if s, present := env["CONTENT_LENGTH"]; present {
		var status int
		length, status = serverLength(s)
		if status != 0 {
			return nil, status
		}
	}
	pairs := [][2]string{}
	for key, value := range env {
		name := ""
		if strings.HasPrefix(key, "HTTP_") {
			name = strings.ReplaceAll(strings.ToLower(key[5:]), "_", "-")
			if name == "" {
				return nil, 400
			}
		} else if key == "CONTENT_TYPE" || key == "CONTENT_LENGTH" {
			name = strings.ReplaceAll(strings.ToLower(key), "_", "-")
		}
		if name == "" {
			continue
		}
		if !httpToken(name) || !serverHeaderValue(value, false) {
			return nil, 400
		}
		pairs = append(pairs, [2]string{name, strings.Trim(value, " \t")})
	}
	sort.Slice(pairs, func(i, j int) bool {
		if pairs[i][0] == pairs[j][0] {
			return pairs[i][1] < pairs[j][1]
		}
		return pairs[i][0] < pairs[j][0]
	})
	headers := make([]Value, len(pairs))
	for i, pair := range pairs {
		headers[i] = makePair(pair[0], pair[1])
	}
	body, status := serverBody(r, length)
	if status != 0 {
		return nil, status
	}
	return &Record{httpRequestType, []Value{method, target, query, headers, body}}, 0
}

func serverError(status int) Value {
	return &Record{httpResponseType, []Value{int64(status), []Value{}, ""}}
}

func serverResponse(value Value, method string, cgi bool) []byte {
	r, ok := value.(*Record)
	if !ok || r.T != httpResponseType || len(r.F) != 3 {
		serverDiagnostic("invalid HTTP response")
		return serverResponse(serverError(500), method, cgi)
	}
	status, headers, body := r.F[0].(int64), r.F[1].([]Value), r.F[2].(string)
	valid := status >= 200 && status <= 599 && utf8.ValidString(body)
	if (status == 204 || status == 205 || status == 304) && body != "" {
		valid = false
	}
	for _, item := range headers {
		pair := item.(*Pair)
		name, value := pair.A.(string), pair.B.(string)
		forbidden := " content-length transfer-encoding connection keep-alive upgrade te trailer "
		if !httpToken(name) || !serverHeaderValue(value, true) || strings.Contains(forbidden, " "+strings.ToLower(name)+" ") {
			valid = false
		}
	}
	if !valid {
		serverDiagnostic("invalid HTTP response")
		return serverResponse(serverError(500), method, cgi)
	}
	reason := http.StatusText(int(status))
	if reason == "" {
		reason = "Unknown"
	}
	prefix := "HTTP/1.1 "
	if cgi {
		prefix = "Status: "
	}
	var b strings.Builder
	fmt.Fprintf(&b, "%s%d %s\r\n", prefix, status, reason)
	for _, item := range headers {
		pair := item.(*Pair)
		fmt.Fprintf(&b, "%s: %s\r\n", pair.A, pair.B)
	}
	fmt.Fprintf(&b, "Content-Length: %d\r\n", len(body))
	if !cgi {
		b.WriteString("Connection: close\r\n")
	}
	b.WriteString("\r\n")
	if method != "HEAD" {
		b.WriteString(body)
	}
	return []byte(b.String())
}

func serverInvoke(entry func(Value) Value, request Value) Value {
	kind, value, fl, ft := outcome(func() Value { return entry(request) })
	out.Flush()
	if kind == "fault" {
		printFault(ft)
		return serverError(500)
	}
	if kind == "fail" {
		serverDiagnostic(fl.String())
		return serverError(500)
	}
	return value
}

func serverCGI(entry func(Value) Value) {
	env := map[string]string{}
	for _, s := range os.Environ() {
		key, value, _ := strings.Cut(s, "=")
		env[key] = value
	}
	request, status := serverCGIRequest(env, os.Stdin)
	response, method := serverError(status), env["REQUEST_METHOD"]
	if status == 0 {
		response = serverInvoke(entry, request)
	}
	os.Stdout.Write(serverResponse(response, method, true))
}
