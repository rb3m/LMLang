// Sequential HTTP/1 listener with explicit framing, limits and deadlines (ADR-076).
package main

import (
	"bufio"
	"fmt"
	"io"
	"net"
	"os"
	"strconv"
	"strings"
	"time"
	"unicode/utf8"
)

const (
	serverHeaderTimeout  = 10 * time.Second
	serverRequestTimeout = 30 * time.Second
)

func serverHeaders(reader *bufio.Reader) ([]string, int) {
	block := make([]byte, 0, 4096)
	for len(block) < httpHeaderLimit {
		b, err := reader.ReadByte()
		if err != nil {
			if e, ok := err.(net.Error); ok && e.Timeout() {
				return nil, 408
			}
			return nil, 400
		}
		block = append(block, b)
		n := len(block)
		if n >= 4 && block[n-4] == '\r' && block[n-3] == '\n' && block[n-2] == '\r' && b == '\n' {
			return strings.Split(string(block[:n-4]), "\r\n"), 0
		}
	}
	return nil, 431
}

func serverReadRequest(conn net.Conn, reader *bufio.Reader) (Value, int) {
	started := time.Now()
	headerDeadline := started.Add(serverHeaderTimeout)
	requestDeadline := started.Add(serverRequestTimeout)
	if requestDeadline.Before(headerDeadline) {
		headerDeadline = requestDeadline
	}
	conn.SetReadDeadline(headerDeadline)
	lines, status := serverHeaders(reader)
	if status != 0 {
		return nil, status
	}
	if time.Now().After(headerDeadline) {
		return nil, 408
	}
	first := lines[0]
	lines = lines[1:]
	parts := strings.Split(first, " ")
	if len(parts) != 3 {
		return nil, 400
	}
	method, raw, version := parts[0], parts[1], parts[2]
	if version != "HTTP/1.0" && version != "HTTP/1.1" {
		return nil, 505
	}
	if !httpToken(method) {
		return nil, 400
	}
	if method == "CONNECT" {
		return nil, 501
	}
	if len(lines) > httpHeaderFields {
		return nil, 431
	}
	headers := []Value{}
	lengths, transfer, expect := []string{}, false, false
	for _, line := range lines {
		name, value, present := strings.Cut(line, ":")
		if !present || !httpToken(name) || !serverHeaderValue(value, false) {
			return nil, 400
		}
		name, value = strings.ToLower(name), strings.Trim(value, " \t")
		headers = append(headers, makePair(name, httpLatin1(value)))
		switch name {
		case "content-length":
			lengths = append(lengths, value)
		case "transfer-encoding":
			transfer = true
		case "expect":
			expect = expect || strings.EqualFold(value, "100-continue")
		}
	}
	if transfer && len(lengths) != 0 {
		return nil, 400
	}
	if transfer {
		return nil, 501
	}
	if len(lengths) > 1 {
		return nil, 400
	}
	var length int64
	if len(lengths) == 1 {
		length, status = serverLength(lengths[0])
		if status != 0 {
			return nil, status
		}
	}
	target, valid := serverTarget(raw)
	if !valid {
		return nil, 400
	}
	_, query, _ := strings.Cut(raw, "?")
	if !utf8.ValidString(query) {
		return nil, 400
	}
	conn.SetDeadline(requestDeadline)
	if expect {
		if _, err := io.WriteString(conn, "HTTP/1.1 100 Continue\r\n\r\n"); err != nil {
			return nil, 400
		}
	}
	body, status := serverBody(reader, length)
	if time.Now().After(requestDeadline) {
		return nil, 408
	}
	if status != 0 {
		return nil, status
	}
	return &Record{httpRequestType, []Value{method, target, query, headers, body}}, 0
}

func serverConnection(conn net.Conn, entry func(Value) Value) {
	defer conn.Close()
	request, status := serverReadRequest(conn, bufio.NewReader(conn))
	response, method := serverError(status), ""
	if status == 0 {
		method = getField(request, "method").(string)
		response = serverInvoke(entry, request)
	}
	conn.SetWriteDeadline(time.Now().Add(serverRequestTimeout))
	conn.Write(serverResponse(response, method, false))
}

func serverLoopback(host string) bool {
	if host == "localhost" {
		return true
	}
	ip := net.ParseIP(host)
	return ip != nil && ip.IsLoopback()
}

func serverListen(entry func(Value) Value, host string, port int, public bool) int {
	if !public && !serverLoopback(host) {
		fmt.Fprintln(os.Stderr, "non-loopback --host requires --public")
		return 2
	}
	listener, err := net.Listen("tcp", net.JoinHostPort(host, strconv.Itoa(port)))
	if err != nil {
		fmt.Fprintln(os.Stderr, "cannot listen:", err)
		return 2
	}
	defer listener.Close()
	actual := listener.Addr().(*net.TCPAddr).Port
	fmt.Fprintf(os.Stderr, "listening on http://%s\n", net.JoinHostPort(host, strconv.Itoa(actual)))
	for {
		conn, err := listener.Accept()
		if err != nil {
			fmt.Fprintln(os.Stderr, "cannot accept:", err)
			return 2
		}
		serverConnection(conn, entry)
	}
}
