package main

import (
	"bufio"
	"io"
	"net"
	"strings"
	"testing"
	"time"
)

func TestServerCGI(t *testing.T) {
	env := map[string]string{"REQUEST_METHOD": "POST", "REQUEST_URI": "/raw?q=x", "QUERY_STRING": "q=x", "CONTENT_LENGTH": "2", "HTTP_Z": " z ", "HTTP_A": "a"}
	req, status := serverCGIRequest(env, strings.NewReader("é"))
	if status != 0 || getField(req, "body") != "é" || getField(req, "target") != "/raw" {
		t.Fatalf("request: %v %v", req, status)
	}
	pairs := getField(req, "headers").([]Value)
	if pairs[0].(*Pair).A != "a" || pairs[2].(*Pair).B != "z" {
		t.Fatal(show(req))
	}
	env["REQUEST_URI"] = "bad"
	env["CONTENT_LENGTH"] = "8388609"
	if _, status = serverCGIRequest(env, strings.NewReader("")); status != 400 {
		t.Fatal(status)
	}
	delete(env, "REQUEST_URI")
	if _, status = serverCGIRequest(env, strings.NewReader("")); status != 500 {
		t.Fatal(status)
	}
}

func TestServerFrames(t *testing.T) {
	response := &Record{httpResponseType, []Value{int64(200), []Value{makePair("X-Test", "ok")}, "é"}}
	want := "Status: 200 OK\r\nX-Test: ok\r\nContent-Length: 2\r\n\r\né"
	if got := string(serverResponse(response, "GET", true)); got != want {
		t.Fatalf("%q", got)
	}
	want = "HTTP/1.1 200 OK\r\nX-Test: ok\r\nContent-Length: 2\r\nConnection: close\r\n\r\n"
	if got := string(serverResponse(response, "HEAD", false)); got != want {
		t.Fatalf("%q", got)
	}
	for _, bad := range []Value{
		&Record{httpResponseType, []Value{int64(204), []Value{}, "bad"}},
		&Record{httpResponseType, []Value{int64(205), []Value{}, "bad"}},
		&Record{httpResponseType, []Value{int64(304), []Value{}, "bad"}},
		&Record{httpResponseType, []Value{int64(199), []Value{}, ""}},
		&Record{httpResponseType, []Value{int64(600), []Value{}, ""}},
		&Record{httpResponseType, []Value{int64(200), []Value{makePair("Connection", "close")}, ""}},
		&Record{httpResponseType, []Value{int64(200), []Value{makePair("X", "a\nb")}, ""}},
		&Record{httpResponseType, []Value{int64(200), []Value{makePair("X", "a\rb")}, ""}},
		&Record{httpResponseType, []Value{int64(200), []Value{makePair("X", "é")}, ""}},
	} {
		if got := string(serverResponse(bad, "GET", true)); got != "Status: 500 Internal Server Error\r\nContent-Length: 0\r\n\r\n" {
			t.Fatalf("%q", got)
		}
	}
	for _, name := range []string{"Content-Length", "Transfer-Encoding", "cOnNeCtIoN", "Keep-Alive", "Upgrade", "TE", "Trailer"} {
		response := &Record{httpResponseType, []Value{int64(200), []Value{makePair(name, "x")}, ""}}
		if got := string(serverResponse(response, "GET", true)); got != "Status: 500 Internal Server Error\r\nContent-Length: 0\r\n\r\n" {
			t.Fatalf("framing header %s: %q", name, got)
		}
	}
}

func TestServerParser(t *testing.T) {
	cases := []struct {
		wire   string
		status int
	}{
		{"GET / HTTP/1.1\r\n\r\n", 0},
		{"get / HTTP/1.0\r\nContent-Length: 000\r\n\r\n", 0},
		{"GET http://localhost/ HTTP/1.1\r\n\r\n", 400},
		{"GET /?bad=\xff HTTP/1.1\r\n\r\n", 400},
		{"GET / HTTP/1.1\r\nX: a\x00b\r\n\r\n", 400},
		{"GET / HTTP/2.0\r\n\r\n", 505},
		{"GET / HTTP/2\n\r\n\r\n", 505},
		{"CONNECT / HTTP/2.0\r\n\r\n", 505},
		{"CONNECT / HTTP/1.1\r\n" + strings.Repeat("X: a\r\n", 101) + "\r\n", 501},
		{"GET bad HTTP/1.1\r\nContent-Length: 8388609\r\n\r\n", 413},
		{"GET / HTTP/1.1\r\n" + strings.Repeat("X: a\r\n", 100) + "\r\n", 0},
		{"GET / HTTP/1.1\r\nX: " + strings.Repeat("a", 65536-len("GET / HTTP/1.1\r\nX: \r\n\r\n")) + "\r\n\r\n", 0},
		{"CONNECT / HTTP/1.1\r\n\r\n", 501},
		{"GET / HTTP/1.1\r\nTransfer-Encoding: chunked\r\n\r\n", 501},
		{"GET / HTTP/1.1\r\nTransfer-Encoding: chunked\r\nContent-Length: 0\r\n\r\n", 400},
		{"GET / HTTP/1.1\r\nContent-Length: 0\r\nContent-Length: 0\r\n\r\n", 400},
		{"GET / HTTP/1.1\r\nContent-Length: 0\r\nContent-Length: 1\r\n\r\n", 400},
		{"GET / HTTP/1.1\r\nContent-Length: +0\r\n\r\n", 400},
		{"GET / HTTP/1.1\r\nContent-Length: x\r\n\r\n", 400},
		{"GET / HTTP/1.1\r\nContent-Length: 8388609\r\n\r\n", 413},
		{"GET / HTTP/1.1\r\n" + strings.Repeat("X: a\r\n", 101) + "\r\n", 431},
		{"GET / HTTP/1.1\r\nX: " + strings.Repeat("a", 65536) + "\r\n\r\n", 431},
		{"POST / HTTP/1.1\r\nContent-Length: 1\r\n\r\n\xff", 400},
	}
	for _, c := range cases {
		a, b := net.Pipe()
		go func() { io.WriteString(b, c.wire); b.Close() }()
		_, status := serverReadRequest(a, bufio.NewReader(a))
		a.Close()
		if status != c.status {
			t.Fatalf("wire %q: %d != %d", c.wire[:min(len(c.wire), 70)], status, c.status)
		}
	}
}

func TestServerDeadline(t *testing.T) {
	a, b := net.Pipe()
	defer a.Close()
	defer b.Close()
	if _, status := serverReadRequest(a, bufio.NewReader(a)); status != 408 {
		t.Fatal(status)
	}
}

func TestServerExpectAndDuplicates(t *testing.T) {
	a, b := net.Pipe()
	defer a.Close()
	defer b.Close()
	result := make(chan Value, 1)
	go func() {
		req, status := serverReadRequest(a, bufio.NewReader(a))
		if status != 0 {
			result <- status
			return
		}
		result <- req
	}()
	io.WriteString(b, "POST /raw%20path?q=é HTTP/1.1\r\nExpect: 100-continue\r\nContent-Length: 2\r\nX-Z: one\r\nx-z: two\r\n\r\n")
	interim := make([]byte, len("HTTP/1.1 100 Continue\r\n\r\n"))
	io.ReadFull(b, interim)
	if string(interim) != "HTTP/1.1 100 Continue\r\n\r\n" {
		t.Fatal(string(interim))
	}
	io.WriteString(b, "é")
	request := <-result
	if _, bad := request.(int); bad {
		t.Fatal(request)
	}
	if getField(request, "target") != "/raw%20path" || getField(request, "query") != "q=é" || getField(request, "body") != "é" {
		t.Fatal(show(request))
	}
	headers := getField(request, "headers").([]Value)
	if headers[2].(*Pair).A != "x-z" || headers[2].(*Pair).B != "one" || headers[3].(*Pair).B != "two" {
		t.Fatal(show(request))
	}
}

func serverTestExchange(wire string, entry func(Value) Value) string {
	a, b := net.Pipe()
	go serverConnection(a, entry)
	io.WriteString(b, wire)
	data, _ := io.ReadAll(b)
	b.Close()
	return string(data)
}

func TestServerFaultRecoveryAndTimeoutResponse(t *testing.T) {
	called := 0
	handler := func(req Value) Value {
		called++
		if called == 1 {
			fault("E-REQUIRES-VIOLATED", -1, "test handler fault", "")
		}
		return &Record{httpResponseType, []Value{int64(200), []Value{}, "ok"}}
	}
	wire := "GET / HTTP/1.1\r\n\r\n"
	if got := serverTestExchange(wire, handler); !strings.HasPrefix(got, "HTTP/1.1 500 ") {
		t.Fatal(got)
	}
	if got := serverTestExchange(wire, handler); !strings.HasSuffix(got, "\r\n\r\nok") {
		t.Fatal(got)
	}
	if called != 2 {
		t.Fatal(called)
	}
	if got := serverTestExchange("", handler); !strings.HasPrefix(got, "HTTP/1.1 408 ") {
		t.Fatal(got)
	}
	if called != 2 {
		t.Fatal("timeout reached handler")
	}
}

func TestServerBodyDeadline(t *testing.T) {
	a, b := net.Pipe()
	defer a.Close()
	defer b.Close()
	go io.WriteString(b, "POST / HTTP/1.1\r\nContent-Length: 2\r\n\r\nx")
	if _, status := serverReadRequest(a, bufio.NewReader(a)); status != 408 {
		t.Fatal(status)
	}
}

func TestServerIncompleteLFDeadline(t *testing.T) {
	a, b := net.Pipe()
	defer a.Close()
	defer b.Close()
	go io.WriteString(b, "GET / HTTP/1.1\n")
	if _, status := serverReadRequest(a, bufio.NewReader(a)); status != 408 {
		t.Fatal(status)
	}
}

type serverDelayedReader struct{ reader io.Reader }

func (r *serverDelayedReader) Read(p []byte) (int, error) {
	time.Sleep(serverRequestTimeout + 10*time.Millisecond)
	return r.reader.Read(p)
}

func TestServerBufferedBodyDeadline(t *testing.T) {
	a, b := net.Pipe()
	defer a.Close()
	defer b.Close()
	reader := &serverDelayedReader{strings.NewReader("POST / HTTP/1.1\r\nContent-Length: 1\r\n\r\nx")}
	if _, status := serverReadRequest(a, bufio.NewReader(reader)); status != 408 {
		t.Fatal(status)
	}
}

type serverHeaderDelayedReader struct{ reader io.Reader }

func (r *serverHeaderDelayedReader) Read(p []byte) (int, error) {
	time.Sleep(serverHeaderTimeout + 10*time.Millisecond)
	return r.reader.Read(p)
}

func TestServerBufferedHeaderDeadline(t *testing.T) {
	a, b := net.Pipe()
	defer a.Close()
	defer b.Close()
	reader := &serverHeaderDelayedReader{strings.NewReader("GET / HTTP/1.1\r\n\r\n")}
	if _, status := serverReadRequest(a, bufio.NewReader(reader)); status != 408 {
		t.Fatal(status)
	}
}
