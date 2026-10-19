// Capture raw HTTP/1 header fields, including framing metadata net/http removes.
package main

import (
	"errors"
	"net"
	"strconv"
	"strings"
)

type httpWire struct {
	net.Conn
	line      []byte
	pairs     [][2]string
	bytes     int
	fields    int
	status    int
	done      bool
	head      bool
	chunkMode byte
	remaining uint64
	problem   string
}

func httpLatin1(s string) string {
	runes := make([]rune, len(s))
	for i := 0; i < len(s); i++ {
		runes[i] = rune(s[i])
	}
	return string(runes)
}

func (c *httpWire) fieldLine(line string, wireBytes int, trailer bool) {
	c.bytes += wireBytes
	c.fields++
	if c.bytes > httpHeaderLimit || c.fields > httpHeaderFields {
		c.problem = "limit"
		return
	}
	name, value, ok := strings.Cut(line, ":")
	if !ok || !httpToken(name) {
		c.problem = "connect"
		return
	}
	for _, b := range []byte(value) {
		if b < 32 && b != '\t' || b == 127 {
			c.problem = "connect"
			return
		}
	}
	if !trailer {
		c.pairs = append(c.pairs, [2]string{strings.ToLower(name), httpLatin1(strings.Trim(value, " \t"))})
	}
}

func (c *httpWire) lineTooLarge(field bool) bool {
	if len(c.line) > httpHeaderLimit {
		return true
	}
	if !field {
		return false
	}
	// The empty terminator does not consume any field budget.
	line := string(c.line)
	if line == "\r" || line == "\n" || line == "\r\n" {
		return false
	}
	return len(c.line)+c.bytes > httpHeaderLimit
}

func (c *httpWire) headerLine(line string, wireBytes int) {
	if c.status == 0 {
		parts := strings.SplitN(line, " ", 3)
		if len(parts) < 2 {
			c.problem = "connect"
			return
		}
		c.status, _ = strconv.Atoi(parts[1])
		if c.status == 0 {
			c.problem = "connect"
		}
		return
	}
	if line != "" {
		c.fieldLine(line, wireBytes, false)
		return
	}
	if c.status >= 100 && c.status < 200 && c.status != 101 {
		c.status, c.pairs = 0, nil
		return
	}
	c.done = true
	if c.head || c.status < 200 || c.status == 204 || c.status == 304 {
		return
	}
	for _, pair := range c.pairs {
		if pair[0] == "transfer-encoding" && strings.EqualFold(pair[1], "chunked") {
			c.chunkMode = 's'
		}
	}
}

func (c *httpWire) chunkByte(b byte) {
	if c.chunkMode == 'b' {
		c.remaining--
		if c.remaining == 0 {
			c.chunkMode = 'e'
		}
		return
	}
	c.line = append(c.line, b)
	if c.lineTooLarge(c.chunkMode == 't') {
		c.problem = "limit"
		return
	}
	if b != '\n' {
		return
	}
	line := strings.TrimSuffix(strings.TrimSuffix(string(c.line), "\n"), "\r")
	switch c.chunkMode {
	case 's':
		size, _, _ := strings.Cut(line, ";")
		n, err := strconv.ParseUint(size, 16, 64)
		if err != nil {
			c.problem = "connect"
			break
		}
		c.remaining, c.chunkMode = n, 'b'
		if n == 0 {
			c.chunkMode = 't'
		}
	case 'e':
		if line != "" {
			c.problem = "connect"
		}
		c.chunkMode = 's'
	case 't':
		if line == "" {
			c.chunkMode = 0
			break
		}
		c.fieldLine(line, len(c.line), true)
	}
	c.line = c.line[:0]
}

func (c *httpWire) Read(p []byte) (int, error) {
	n, err := c.Conn.Read(p)
	for _, b := range p[:n] {
		if c.problem != "" {
			break
		}
		if c.done {
			if c.chunkMode == 0 {
				break
			}
			c.chunkByte(b)
			continue
		}
		c.line = append(c.line, b)
		if c.lineTooLarge(c.status != 0) {
			c.problem = "limit"
			break
		}
		if b == '\n' {
			line := strings.TrimSuffix(strings.TrimSuffix(string(c.line), "\n"), "\r")
			c.headerLine(line, len(c.line))
			c.line = c.line[:0]
		}
	}
	if c.problem != "" {
		return 0, errors.New("HTTP response " + c.problem)
	}
	return n, err
}
