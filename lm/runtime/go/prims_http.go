// HTTP client: fixed capabilities and limits, no ambient proxy or TLS overrides.
package main

import (
	"context"
	"crypto/tls"
	"errors"
	"io"
	"net"
	"net/http"
	"net/url"
	"sort"
	"strconv"
	"strings"
	"time"
	"unicode/utf8"
)

const (
	httpBodyLimit      = 8 << 20
	httpHeaderLimit    = 64 << 10
	httpHeaderFields   = 100
	httpConnectTimeout = 5 * time.Second
	httpTotalTimeout   = 30 * time.Second
)

var httpResponseType = &RecType{"http.Response", []string{"status", "headers", "body"}}

func httpFail(raw, category string) { lmFail("http.HttpError", raw, category) }

func httpToken(s string) bool {
	if s == "" {
		return false
	}
	for _, c := range s {
		if c >= 'a' && c <= 'z' || c >= 'A' && c <= 'Z' || c >= '0' && c <= '9' || strings.ContainsRune("!#$%&'*+-.^_`|~", c) {
			continue
		}
		return false
	}
	return true
}

func httpURL(raw string) (*url.URL, bool) {
	for i, c := range raw {
		if c <= 32 || c >= 127 || c == '\\' {
			return nil, false
		}
		if c == '%' {
			if i+2 >= len(raw) {
				return nil, false
			}
			if _, err := strconv.ParseUint(raw[i+1:i+3], 16, 8); err != nil {
				return nil, false
			}
		}
	}
	u, err := url.Parse(raw)
	if err != nil || u.Opaque != "" || u.User != nil || strings.Contains(raw, "#") || u.Host == "" {
		return nil, false
	}
	u.Scheme = strings.ToLower(u.Scheme)
	if u.Scheme != "https" && u.Scheme != "http" {
		return nil, false
	}
	host := strings.ToLower(u.Hostname())
	if host == "" || strings.ContainsAny(host, "%\\") || strings.HasSuffix(u.Host, ":") {
		return nil, false
	}
	if strings.Contains(host, ":") && net.ParseIP(host) == nil {
		return nil, false
	}
	if strings.HasPrefix(u.Host, "[") && !strings.Contains(host, ":") {
		return nil, false
	}
	if port := u.Port(); port != "" {
		for _, c := range port {
			if c < '0' || c > '9' {
				return nil, false
			}
		}
		n, err := strconv.Atoi(port)
		if err != nil || n < 1 || n > 65535 {
			return nil, false
		}
	}
	if u.Scheme == "https" || host == "localhost" || host == "::1" {
		return u, true
	}
	ip := net.ParseIP(host)
	return u, !strings.Contains(host, ":") && ip != nil && ip.To4() != nil && ip.To4()[0] == 127
}

func httpCategory(err error, ctx context.Context, tlsFailed bool) string {
	var timeout net.Error
	if ctx.Err() != nil || errors.As(err, &timeout) && timeout.Timeout() {
		return "timeout"
	}
	var dns *net.DNSError
	if errors.As(err, &dns) {
		return "dns"
	}
	if tlsFailed {
		return "tls"
	}
	return "connect"
}

func prim_http_request(method, rawURL, headers, body Value) Value {
	raw := rawURL.(string)
	u, valid := httpURL(raw)
	for _, c := range method.(string) {
		if c >= 127 {
			httpFail(raw, "invalid-request")
		}
	}
	m := strings.ToUpper(method.(string))
	if !valid || !strings.Contains(" GET HEAD POST PUT PATCH DELETE OPTIONS ", " "+m+" ") || m == "" {
		httpFail(raw, "invalid-request")
	}
	h := http.Header{}
	size := len(body.(string))
	for _, item := range headers.([]Value) {
		pair := item.(*Pair)
		name, value := pair.A.(string), pair.B.(string)
		lower := strings.ToLower(name)
		if !httpToken(name) || lower == "host" || lower == "content-length" || lower == "transfer-encoding" || lower == "connection" {
			httpFail(raw, "invalid-request")
		}
		for _, c := range value {
			if c < 32 && c != '\t' || c == 127 {
				httpFail(raw, "invalid-request")
			}
		}
		size += len(name) + len(value)
		h.Add(name, value)
	}
	if size > httpBodyLimit {
		httpFail(raw, "limit")
	}
	// A nil User-Agent slice suppresses Go's automatic identifying header.
	if _, present := h["User-Agent"]; !present {
		h["User-Agent"] = nil
	}
	ctx, cancel := context.WithTimeout(context.Background(), httpTotalTimeout)
	defer cancel()
	var wire *httpWire
	tlsFailed := false
	dial := func(_ context.Context, network, address string) (net.Conn, error) {
		host, port, err := net.SplitHostPort(address)
		if err != nil {
			return nil, err
		}
		localhost := strings.EqualFold(host, "localhost")
		if localhost {
			address = net.JoinHostPort("127.0.0.1", port)
		}
		connectCtx, connectCancel := context.WithTimeout(ctx, httpConnectTimeout)
		defer connectCancel()
		conn, err := (&net.Dialer{Timeout: httpConnectTimeout}).DialContext(connectCtx, network, address)
		if err != nil && localhost && connectCtx.Err() == nil {
			address = net.JoinHostPort("::1", port)
			conn, err = (&net.Dialer{Timeout: httpConnectTimeout}).DialContext(connectCtx, network, address)
		}
		if err != nil {
			return nil, err
		}
		if deadline, ok := ctx.Deadline(); ok {
			conn.SetDeadline(deadline)
		}
		if u.Scheme == "https" {
			roots, err := httpSystemRoots()
			if err != nil {
				conn.Close()
				tlsFailed = true
				return nil, err
			}
			t := tls.Client(conn, &tls.Config{ServerName: u.Hostname(), RootCAs: roots, MinVersion: tls.VersionTLS12})
			if err := t.HandshakeContext(ctx); err != nil {
				conn.Close()
				tlsFailed = true
				return nil, err
			}
			conn = t
		}
		wire = &httpWire{Conn: conn, head: m == "HEAD"}
		return wire, nil
	}
	transport := &http.Transport{DialContext: dial, DialTLSContext: dial, DisableCompression: true,
		DisableKeepAlives: true, MaxResponseHeaderBytes: 2 * httpHeaderLimit, ReadBufferSize: httpHeaderLimit + 2}
	defer transport.CloseIdleConnections()
	client := &http.Client{Transport: transport, CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}
	req, err := http.NewRequestWithContext(ctx, m, u.String(), strings.NewReader(body.(string)))
	if err != nil {
		httpFail(raw, "invalid-request")
	}
	req.Header = h
	resp, err := client.Do(req)
	if err != nil {
		if wire != nil && wire.problem != "" {
			httpFail(raw, wire.problem)
		}
		httpFail(raw, httpCategory(err, ctx, tlsFailed))
	}
	defer resp.Body.Close()
	if m != "HEAD" && resp.StatusCode != 204 && resp.StatusCode != 304 && resp.ContentLength > httpBodyLimit {
		httpFail(raw, "limit")
	}
	data := []byte{}
	if m != "HEAD" && resp.StatusCode >= 200 && resp.StatusCode != 204 && resp.StatusCode != 304 {
		data, err = io.ReadAll(io.LimitReader(resp.Body, httpBodyLimit+1))
	}
	if err != nil {
		if wire.problem != "" {
			httpFail(raw, wire.problem)
		}
		httpFail(raw, httpCategory(err, ctx, false))
	}
	if len(data) > httpBodyLimit {
		httpFail(raw, "limit")
	}
	if !utf8.Valid(data) {
		httpFail(raw, "invalid-utf8")
	}
	if ctx.Err() != nil {
		httpFail(raw, "timeout")
	}
	sort.SliceStable(wire.pairs, func(i, j int) bool { return wire.pairs[i][0] < wire.pairs[j][0] })
	pairs := make([]Value, len(wire.pairs))
	for i, pair := range wire.pairs {
		pairs[i] = makePair(pair[0], pair[1])
	}
	return &Record{httpResponseType, []Value{int64(resp.StatusCode), pairs, string(data)}}
}
