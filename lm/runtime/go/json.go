// Strict RFC 8259 JSON. Grammar and detection positions mirror lm/json_prims.py.
package main

import (
	"fmt"
	"math"
	"strconv"
	"strings"
)

// Generated constructors alias these pointers, so parsed and LM-constructed values agree.
var jsonCtors = map[string]*Ctor{
	"json.JNull": {"json.JNull"}, "json.JBool": {"json.JBool"},
	"json.JInt": {"json.JInt"}, "json.JFloat": {"json.JFloat"},
	"json.JStr": {"json.JStr"}, "json.JArr": {"json.JArr"}, "json.JObj": {"json.JObj"},
}

func jsonVariant(name string, args ...Value) Value {
	return &Variant{jsonCtors["json."+name], args}
}

type jsonParser struct {
	s []rune
	i int
}

func (p *jsonParser) bad(msg string) { lmFail("json.BadJson", int64(p.i), msg) }
func (p *jsonParser) peek() rune {
	if p.i == len(p.s) {
		return -1
	}
	return p.s[p.i]
}
func (p *jsonParser) required() rune {
	c := p.peek()
	if c == -1 {
		p.bad("unexpected end")
	}
	return c
}
func (p *jsonParser) space() {
	for strings.ContainsRune(" \t\r\n", p.peek()) {
		p.i++
	}
}
func (p *jsonParser) expect(c rune) {
	if p.required() != c {
		p.bad("unexpected character")
	}
	p.i++
}
func (p *jsonParser) hex4() rune {
	var n rune
	for i := 0; i < 4; i++ {
		c := p.required()
		d := strings.IndexRune("0123456789abcdef", c)
		if d < 0 {
			d = strings.IndexRune("0123456789ABCDEF", c)
		}
		if d < 0 {
			p.bad("bad escape")
		}
		n = n*16 + rune(d)
		p.i++
	}
	return n
}
func (p *jsonParser) str() string {
	p.expect('"')
	var out strings.Builder
	for {
		c := p.required()
		if c == '"' {
			p.i++
			return out.String()
		}
		if c < 32 {
			p.bad("control character in string")
		}
		p.i++
		if c != '\\' {
			out.WriteRune(c)
			continue
		}
		c = p.required()
		escapes := map[rune]rune{'"': '"', '\\': '\\', '/': '/', 'b': '\b', 'f': '\f', 'n': '\n', 'r': '\r', 't': '\t'}
		if v, ok := escapes[c]; ok {
			out.WriteRune(v)
			p.i++
			continue
		}
		if c != 'u' {
			p.bad("bad escape")
		}
		p.i++
		n := p.hex4()
		if n >= 0xD800 && n <= 0xDBFF {
			if p.i+2 > len(p.s) || p.s[p.i] != '\\' || p.s[p.i+1] != 'u' {
				p.bad("unpaired surrogate")
			}
			p.i += 2
			lo := p.hex4()
			if lo < 0xDC00 || lo > 0xDFFF {
				p.bad("unpaired surrogate")
			}
			n = 0x10000 + ((n - 0xD800) << 10) + lo - 0xDC00
		} else if n >= 0xDC00 && n <= 0xDFFF {
			p.bad("unpaired surrogate")
		}
		out.WriteRune(n)
	}
}
func (p *jsonParser) digits() {
	c := p.required()
	if c < '0' || c > '9' {
		p.bad("unexpected character")
	}
	for p.peek() >= '0' && p.peek() <= '9' {
		p.i++
	}
}
func (p *jsonParser) number() Value {
	start := p.i
	if p.peek() == '-' {
		p.i++
	}
	if p.required() == '0' {
		p.i++
	} else {
		p.digits()
	}
	integer := true
	if p.peek() == '.' {
		integer = false
		p.i++
		p.digits()
	}
	if p.peek() == 'e' || p.peek() == 'E' {
		integer = false
		p.i++
		if p.peek() == '+' || p.peek() == '-' {
			p.i++
		}
		p.digits()
	}
	text := string(p.s[start:p.i])
	if integer {
		if n, e := strconv.ParseInt(text, 10, 64); e == nil {
			return jsonVariant("JInt", n)
		}
	}
	n, _ := strconv.ParseFloat(text, 64)
	if math.IsInf(n, 0) || math.IsNaN(n) {
		p.bad("number out of range")
	}
	if n == 0 {
		n = 0
	}
	return jsonVariant("JFloat", n)
}

type jsonFrame struct {
	kind rune
	arr  []Value
	obj  *node
	key  string
}

func (f *jsonFrame) value() Value {
	if f.kind == '[' {
		return jsonVariant("JArr", f.arr)
	}
	return jsonVariant("JObj", &Coll{f.obj, false})
}
func (p *jsonParser) key(f *jsonFrame) {
	f.key = p.str()
	if find(f.obj, f.key) != nil {
		p.bad("duplicate key")
	}
	p.space()
	p.expect(':')
}
func (p *jsonParser) value() Value {
	stack := []*jsonFrame{}
	for {
		p.space()
		c := p.required()
		var v Value
		if c == '[' || c == '{' {
			p.i++
			f := &jsonFrame{kind: c, arr: []Value{}}
			stack = append(stack, f)
			p.space()
			close := ']'
			if c == '{' {
				close = '}'
			}
			if p.peek() == close {
				p.i++
				stack = stack[:len(stack)-1]
				v = f.value()
			} else {
				if c == '{' {
					p.key(f)
				}
				continue
			}
		} else if c == '"' {
			v = jsonVariant("JStr", p.str())
		} else if c == '-' || (c >= '0' && c <= '9') {
			v = p.number()
		} else {
			word := map[rune]string{'n': "null", 't': "true", 'f': "false"}[c]
			if word == "" {
				p.bad("unexpected character")
			}
			for _, ch := range word {
				p.expect(ch)
			}
			if word == "null" {
				v = jsonVariant("JNull")
			} else {
				v = jsonVariant("JBool", word == "true")
			}
		}
		for {
			if len(stack) == 0 {
				return v
			}
			f := stack[len(stack)-1]
			if f.kind == '[' {
				f.arr = append(f.arr, v)
			} else {
				f.obj = insert(f.obj, f.key, v)
			}
			p.space()
			close := ']'
			if f.kind == '{' {
				close = '}'
			}
			if p.required() == close {
				p.i++
				stack = stack[:len(stack)-1]
				v = f.value()
				continue
			}
			p.expect(',')
			p.space()
			if f.kind == '{' {
				p.key(f)
			}
			break
		}
	}
}
func prim_json_parse(s Value) Value {
	p := jsonParser{s: []rune(s.(string))}
	v := p.value()
	p.space()
	if p.peek() != -1 {
		p.bad("trailing data")
	}
	return v
}
func jsonQuote(s string) string {
	var out strings.Builder
	out.WriteByte('"')
	for _, c := range s {
		switch c {
		case '"':
			out.WriteString(`\"`)
		case '\\':
			out.WriteString(`\\`)
		case '\b':
			out.WriteString(`\b`)
		case '\f':
			out.WriteString(`\f`)
		case '\n':
			out.WriteString(`\n`)
		case '\r':
			out.WriteString(`\r`)
		case '\t':
			out.WriteString(`\t`)
		default:
			if c < 32 {
				fmt.Fprintf(&out, `\u%04X`, c)
			} else {
				out.WriteRune(c)
			}
		}
	}
	out.WriteByte('"')
	return out.String()
}
func prim_json_print(j Value) Value {
	var out strings.Builder
	pending := []Value{j}
	for len(pending) > 0 {
		v := pending[len(pending)-1]
		pending = pending[:len(pending)-1]
		if s, ok := v.(string); ok {
			out.WriteString(s)
			continue
		}
		x := v.(*Variant)
		switch x.C.Name {
		case "json.JNull":
			out.WriteString("null")
		case "json.JBool":
			out.WriteString(strconv.FormatBool(x.Args[0].(bool)))
		case "json.JInt":
			out.WriteString(strconv.FormatInt(x.Args[0].(int64), 10))
		case "json.JFloat":
			out.WriteString(showFloat(x.Args[0].(float64)))
		case "json.JStr":
			out.WriteString(jsonQuote(x.Args[0].(string)))
		default:
			tokens := []Value{}
			if x.C.Name == "json.JObj" {
				out.WriteByte('{')
				walk(root(x.Args[0]), func(k, v Value) {
					if len(tokens) > 0 {
						tokens = append(tokens, ",")
					}
					tokens = append(tokens, jsonQuote(k.(string)), ":", v)
				})
				tokens = append(tokens, "}")
			} else {
				out.WriteByte('[')
				for i, v := range x.Args[0].([]Value) {
					if i > 0 {
						tokens = append(tokens, ",")
					}
					tokens = append(tokens, v)
				}
				tokens = append(tokens, "]")
			}
			for i := len(tokens) - 1; i >= 0; i-- {
				pending = append(pending, tokens[i])
			}
		}
	}
	return out.String()
}
