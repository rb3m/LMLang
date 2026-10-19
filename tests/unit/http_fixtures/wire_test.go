package main

import (
	"bufio"
	"context"
	"crypto/tls"
	"io"
	"net"
	"net/http"
	"os"
	"strings"
	"testing"
	"time"
)

var testResponse string
var testDelay time.Duration
var testBodyDelay time.Duration
var testDrip bool
var testTLS bool
var testRejectIPv4 bool
var testDialAddresses []string

func httpTestDial(ctx context.Context, network, address string) (net.Conn, error) {
	testDialAddresses = append(testDialAddresses, address)
	if testRejectIPv4 && strings.HasPrefix(address, "127.0.0.1:") {
		return nil, io.ErrClosedPipe
	}
	client, server := net.Pipe()
	response, delay, useTLS := testResponse, testDelay, testTLS
	bodyDelay, drip := testBodyDelay, testDrip
	go func() {
		defer server.Close()
		if useTLS {
			cert, err := tls.LoadX509KeyPair(os.Getenv("LM_TEST_CERT"), os.Getenv("LM_TEST_KEY"))
			if err != nil {
				panic(err)
			}
			serverTLS := tls.Server(server, &tls.Config{Certificates: []tls.Certificate{cert}})
			serverTLS.Handshake()
			return
		}
		request, err := http.ReadRequest(bufio.NewReader(server))
		if err != nil {
			return
		}
		io.Copy(io.Discard, request.Body)
		time.Sleep(delay)
		if bodyDelay != 0 || drip {
			head, body, _ := strings.Cut(response, "\r\n\r\n")
			io.WriteString(server, head+"\r\n\r\n")
			time.Sleep(bodyDelay)
			for _, b := range []byte(body) {
				if drip {
					time.Sleep(600 * time.Millisecond)
				}
				if _, err := server.Write([]byte{b}); err != nil {
					return
				}
			}
			return
		}
		io.WriteString(server, response)
	}()
	return client, nil
}
func httpOutcome(method, address string, headers []Value, body string) (value Value, category string) {
	defer func() {
		if failure := recover(); failure != nil {
			f, ok := failure.(*Fail)
			if !ok {
				panic(failure)
			}
			category = f.Args[1].(string)
		}
	}()
	value = prim_http_request(method, address, headers, body)
	return
}
func TestHTTPClientPipe(t *testing.T) {
	tests := []struct {
		name, method, response, want string
		delay                        time.Duration
		bodyDelay                    time.Duration
		drip                         bool
	}{
		{name: "normal", method: "GET", response: "HTTP/1.1 200 OK\r\nContent-Length: 3\r\n\r\nhi!"},
		{name: "duplicate", method: "GET", response: "HTTP/1.1 200 OK\r\nX-Z: first\r\nx-z: second\r\nX-A: a\r\nContent-Length: 0\r\n\r\n"},
		{name: "chunked", method: "GET", response: "HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n2\r\nhi\r\n0\r\n\r\n"},
		{name: "truncated", method: "GET", response: "HTTP/1.1 200 OK\r\nContent-Length: 5\r\n\r\nx", want: "connect"},
		{name: "limit-declared", method: "GET", response: "HTTP/1.1 200 OK\r\nContent-Length: 8388609\r\n\r\n", want: "limit"},
		{name: "limit-actual", method: "GET", response: "HTTP/1.1 200 OK\r\n\r\n" + strings.Repeat("x", 8388609), want: "limit"},
		{name: "exact-body", method: "GET", response: "HTTP/1.1 200 OK\r\nContent-Length: 8388608\r\n\r\n" + strings.Repeat("x", 8388608)},
		{name: "head", method: "HEAD", response: "HTTP/1.1 200 OK\r\nContent-Length: 8388609\r\n\r\n"},
		{name: "204", method: "GET", response: "HTTP/1.1 204 No Content\r\n\r\n"},
		{name: "101", method: "GET", response: "HTTP/1.1 101 Switching Protocols\r\nConnection: Upgrade\r\nUpgrade: websocket\r\n\r\n"},
		{name: "redirect", method: "GET", response: "HTTP/1.1 302 Found\r\nLocation: /other\r\nContent-Length: 0\r\n\r\n"},
		{name: "utf8", method: "GET", response: "HTTP/1.1 200 OK\r\nContent-Length: 1\r\n\r\n\xff", want: "invalid-utf8"},
		{name: "headers100", method: "GET", response: "HTTP/1.1 200 OK\r\n" + strings.Repeat("X: a\r\n", 99) + "Content-Length: 0\r\n\r\n"},
		{name: "headers101", method: "GET", response: "HTTP/1.1 200 OK\r\n" + strings.Repeat("X: a\r\n", 101) + "\r\n", want: "limit"},
		{name: "headers65536", method: "GET", response: "HTTP/1.1 200 OK\r\nX: " + strings.Repeat("a", 65531) + "\r\n\r\n"},
		{name: "headers65537", method: "GET", response: "HTTP/1.1 200 OK\r\nX: " + strings.Repeat("a", 65532) + "\r\n\r\n", want: "limit"},
		{name: "obsfold", method: "GET", response: "HTTP/1.1 200 OK\r\nX: a\r\n b\r\n\r\n", want: "connect"},
		{name: "latin1", method: "GET", response: "HTTP/1.1 200 OK\r\nX: \xff\xa0\r\nContent-Length: 0\r\n\r\n"},
		{name: "info100", method: "GET", response: "HTTP/1.1 100 Continue\r\n" + strings.Repeat("X: a\r\n", 99) + "\r\nHTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n"},
		{name: "info101", method: "GET", response: "HTTP/1.1 100 Continue\r\n" + strings.Repeat("X: a\r\n", 100) + "\r\nHTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n", want: "limit"},
		{name: "info-bytes-exact", method: "GET", response: "HTTP/1.1 100 Continue\r\nX: " + strings.Repeat("a", 65531) + "\r\n\r\nHTTP/1.1 200 OK\r\n\r\n"},
		{name: "info-bytes-limit", method: "GET", response: "HTTP/1.1 100 Continue\r\nX: " + strings.Repeat("a", 65531) + "\r\n\r\nHTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n", want: "limit"},
		{name: "trailers100", method: "GET", response: "HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n0\r\n" + strings.Repeat("X: a\r\n", 99) + "\r\n"},
		{name: "trailers101", method: "GET", response: "HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n0\r\n" + strings.Repeat("X: a\r\n", 100) + "\r\n", want: "limit"},
		{name: "trailers-bytes-exact", method: "GET", response: "HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n0\r\nX: " + strings.Repeat("a", 65503) + "\r\n\r\n"},
		{name: "trailers-bytes-limit", method: "GET", response: "HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n0\r\nX: " + strings.Repeat("a", 65504) + "\r\n\r\n", want: "limit"},
		{name: "timeout", method: "GET", response: "HTTP/1.1 200 OK\r\n\r\n", want: "timeout", delay: 2500 * time.Millisecond},
		{name: "body-timeout", method: "GET", response: "HTTP/1.1 200 OK\r\nContent-Length: 5\r\n\r\nhello", want: "timeout", bodyDelay: 2500 * time.Millisecond},
		{name: "drip-deadline", method: "GET", response: "HTTP/1.1 200 OK\r\nContent-Length: 5\r\n\r\nhello", want: "timeout", drip: true},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			testResponse, testDelay = test.response, test.delay
			testBodyDelay, testDrip = test.bodyDelay, test.drip
			value, category := httpOutcome(test.method, "http://localhost/", []Value{}, "")
			if category != test.want {
				t.Fatalf("want %q, got %q", test.want, category)
			}
			if category != "" {
				return
			}
			rec := value.(*Record)
			pairs := rec.F[1].([]Value)
			if test.name == "normal" && rec.F[2].(string) != "hi!" {
				t.Fatal(show(value))
			}
			if test.name == "duplicate" && show(pairs) != "(list (pair \"content-length\" \"0\") (pair \"x-a\" \"a\") (pair \"x-z\" \"first\") (pair \"x-z\" \"second\"))" {
				t.Fatal(show(value))
			}
			if test.name == "chunked" && show(pairs) != "(list (pair \"transfer-encoding\" \"chunked\"))" {
				t.Fatal(show(value))
			}
			if test.name == "latin1" && pairs[1].(*Pair).B != "ÿ " {
				t.Fatal(show(value))
			}
			if test.name == "exact-body" && len(rec.F[2].(string)) != 8388608 {
				t.Fatal("body length")
			}
			if test.name == "head" && rec.F[2].(string) != "" {
				t.Fatal("HEAD body")
			}
		})
	}
}

func TestLocalhostFallback(t *testing.T) {
	testResponse = "HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n"
	testDelay, testBodyDelay, testDrip = 0, 0, false
	testRejectIPv4, testDialAddresses = true, nil
	defer func() { testRejectIPv4 = false }()
	if _, category := httpOutcome("GET", "http://localhost/", []Value{}, ""); category != "" {
		t.Fatal(category)
	}
	if strings.Join(testDialAddresses, ",") != "127.0.0.1:80,[::1]:80" {
		t.Fatal(testDialAddresses)
	}
	if httpConnectTimeout != 5*time.Second {
		t.Fatal("connect deadline changed")
	}
}
func TestHTTPInvalidArguments(t *testing.T) {
	for _, address := range []string{"ftp://localhost/", "http://example.com/", "http://user:pass@localhost/", "http://localhost/#", "http://localhost:0/", "http://localhost:65536/", "https://[hello]/", "http://[::2]/", "http://127.0.0.1:/", "http://localhost/é", "http://localhost/?bad=%zz", "http://localhost/back\\slash"} {
		if _, category := httpOutcome("GET", address, []Value{}, ""); category != "invalid-request" {
			t.Errorf("%s: %s", address, category)
		}
	}
	for _, method := range []string{"TRACE", "CONNECT", "bad", "GET HEAD", "poſt", ""} {
		if _, category := httpOutcome(method, "http://localhost/", []Value{}, ""); category != "invalid-request" {
			t.Errorf("%s: %s", method, category)
		}
	}
	for _, header := range [][2]string{{"Host", "x"}, {"X", "a\r\nb"}, {"Connection", "close"}, {"x y", "z"}} {
		if _, category := httpOutcome("GET", "http://localhost/", []Value{makePair(header[0], header[1])}, ""); category != "invalid-request" {
			t.Error(category)
		}
	}
	if _, category := httpOutcome("GET", "http://localhost/", []Value{}, strings.Repeat("a", 8388609)); category != "limit" {
		t.Error(category)
	}
}
func TestHTTPSPipe(t *testing.T) {
	testTLS = true
	defer func() { testTLS = false }()
	if _, category := httpOutcome("GET", "https://localhost/", []Value{}, ""); category != "tls" {
		t.Error(category)
	}
}
