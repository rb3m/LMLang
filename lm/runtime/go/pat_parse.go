// Pattern grammar and scalar error offsets (ADR-075); no host regex engine.
package main

import "strings"

type patRange struct{ lo, hi rune }
type patNode struct {
	op          string
	children    []*patNode
	ranges      []patRange
	neg         bool
	n, m, group int
	lazy        bool
}
type patParser struct {
	s                []rune
	i, groups, depth int
}

func patBad(pos int, reason string) { lmFail("pat.BadPattern", int64(pos), reason) }
func (p *patParser) peek() rune {
	if p.i == len(p.s) {
		return -1
	}
	return p.s[p.i]
}
func patLit(c rune) *patNode { return &patNode{op: "class", ranges: []patRange{{c, c}}} }
func patComplement(rs []patRange) []patRange {
	// Input shorthand ranges are already sorted and disjoint.
	out, lo := []patRange{}, rune(0)
	for _, r := range rs {
		if lo < r.lo {
			out = append(out, patRange{lo, r.lo - 1})
		}
		lo = r.hi + 1
	}
	if lo <= 0x10ffff {
		out = append(out, patRange{lo, 0x10ffff})
	}
	return out
}
func (p *patParser) escape() *patNode {
	pos := p.i
	p.i++
	c := p.peek()
	if c == -1 {
		patBad(pos, "trailing escape")
	}
	p.i++
	base := c
	if base >= 'A' && base <= 'Z' {
		base += 'a' - 'A'
	}
	var rs []patRange
	switch base {
	case 'd':
		rs = []patRange{{'0', '9'}}
	case 'w':
		rs = []patRange{{'0', '9'}, {'A', 'Z'}, {'_', '_'}, {'a', 'z'}}
	case 's':
		rs = []patRange{{9, 13}, {32, 32}}
	}
	if rs != nil {
		if c != base {
			rs = patComplement(rs)
		}
		return &patNode{op: "class", ranges: rs}
	}
	if c == 'n' {
		return patLit('\n')
	}
	if c == 't' {
		return patLit('\t')
	}
	if strings.ContainsRune(`\.^$|?*+()[]{}-`, c) {
		return patLit(c)
	}
	patBad(pos, "unknown escape")
	return nil
}
func (p *patParser) classAtom() *patNode {
	if p.peek() == '\\' {
		return p.escape()
	}
	c := p.peek()
	p.i++
	return patLit(c)
}
func (p *patParser) class() *patNode {
	pos := p.i
	p.i++
	n := &patNode{op: "class"}
	if p.peek() == '^' {
		n.neg = true
		p.i++
	}
	if p.peek() == ']' && p.i+1 == len(p.s) {
		patBad(pos, "empty class")
	}
	first := true
	for {
		if p.peek() == -1 {
			patBad(pos, "unclosed class")
		}
		if p.peek() == ']' && !first {
			p.i++
			return n
		}
		leadingDash := first && p.peek() == '-'
		a := p.classAtom()
		first = false
		if leadingDash || p.peek() != '-' || p.i+1 == len(p.s) || p.s[p.i+1] == ']' {
			n.ranges = append(n.ranges, a.ranges...)
			continue
		}
		dash := p.i
		p.i++
		b := p.classAtom()
		if len(a.ranges) != 1 || a.ranges[0].lo != a.ranges[0].hi || len(b.ranges) != 1 || b.ranges[0].lo != b.ranges[0].hi {
			patBad(dash, "invalid range")
		}
		if a.ranges[0].lo > b.ranges[0].lo {
			patBad(dash, "reversed range")
		}
		n.ranges = append(n.ranges, patRange{a.ranges[0].lo, b.ranges[0].lo})
	}
}
func (p *patParser) atom() *patNode {
	c, pos := p.peek(), p.i
	if strings.ContainsRune("*+?{", c) {
		patBad(pos, "dangling quantifier")
	}
	if c == '[' {
		return p.class()
	}
	if c == '\\' {
		return p.escape()
	}
	p.i++
	switch c {
	case '(':
		p.depth++
		if p.depth > 100 {
			patBad(pos, "nesting limit")
		}
		group := 0
		if p.peek() == '?' {
			if p.i+1 >= len(p.s) || p.s[p.i+1] != ':' {
				patBad(pos, "unsupported group")
			}
			p.i += 2
		} else {
			p.groups++
			group = p.groups
		}
		n := p.alt()
		if p.peek() != ')' {
			patBad(pos, "unclosed group")
		}
		p.i++
		p.depth--
		if group != 0 {
			return &patNode{op: "group", group: group, children: []*patNode{n}}
		}
		return n
	case '.':
		return &patNode{op: "dot"}
	case '^':
		return &patNode{op: "start"}
	case '$':
		return &patNode{op: "end"}
	}
	return patLit(c)
}
func (p *patParser) number(pos int) int {
	if p.peek() < '0' || p.peek() > '9' {
		patBad(pos, "invalid repetition")
	}
	n := 0
	for p.peek() >= '0' && p.peek() <= '9' {
		if n <= 1000 {
			n = n*10 + int(p.peek()-'0')
		}
		p.i++
	}
	if n > 1000 {
		patBad(pos, "repetition bound")
	}
	return n
}
func (p *patParser) repeated() *patNode {
	a := p.atom()
	c, pos := p.peek(), p.i
	if !strings.ContainsRune("*+?{", c) {
		return a
	}
	p.i++
	n, m := 0, -1
	switch c {
	case '+':
		n = 1
	case '?':
		m = 1
	case '{':
		n = p.number(pos)
		m = n
		if p.peek() == ',' {
			p.i++
			m = -1
			if p.peek() != '}' {
				m = p.number(pos)
			}
		}
		if p.peek() != '}' || (m >= 0 && m < n) {
			patBad(pos, "invalid repetition")
		}
		p.i++
		if n > 1000 || m > 1000 {
			patBad(pos, "repetition bound")
		}
	}
	lazy := p.peek() == '?'
	if lazy {
		p.i++
	}
	if strings.ContainsRune("*+?{", p.peek()) {
		patBad(p.i, "dangling quantifier")
	}
	return &patNode{op: "repeat", children: []*patNode{a}, n: n, m: m, lazy: lazy}
}
func (p *patParser) seq() *patNode {
	n := &patNode{op: "seq"}
	for p.peek() != -1 && p.peek() != ')' && p.peek() != '|' {
		n.children = append(n.children, p.repeated())
	}
	return n
}
func (p *patParser) alt() *patNode {
	n := &patNode{op: "alt", children: []*patNode{p.seq()}}
	for p.peek() == '|' {
		p.i++
		n.children = append(n.children, p.seq())
	}
	return n
}
