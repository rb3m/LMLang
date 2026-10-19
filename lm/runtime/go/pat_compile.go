// Thompson program construction; expanded programs have at most 10000 instructions.
package main

type patInst struct {
	op         string
	x, y, slot int
	ranges     []patRange
	neg        bool
	scope      []int
}
type Pat struct {
	code                 []patInst
	start, groups, loops int
	scope                []int
}

func (p *Pat) emit(i patInst) int {
	if len(p.code) == 10000 {
		patBad(0, "program limit")
	}
	i.scope = append([]int(nil), p.scope...)
	p.code = append(p.code, i)
	return len(p.code) - 1
}
func (p *Pat) split(a, b int, lazy bool) int {
	if lazy {
		a, b = b, a
	}
	return p.emit(patInst{op: "split", x: a, y: b})
}
func (p *Pat) compile(n *patNode, next int) int {
	switch n.op {
	case "seq":
		for i := len(n.children) - 1; i >= 0; i-- {
			next = p.compile(n.children[i], next)
		}
		return next
	case "alt":
		last := len(n.children) - 1
		out := p.compile(n.children[last], next)
		for i := last - 1; i >= 0; i-- {
			out = p.split(p.compile(n.children[i], next), out, false)
		}
		return out
	case "group":
		end := p.emit(patInst{op: "save", slot: 2*n.group + 1, x: next})
		body := p.compile(n.children[0], end)
		return p.emit(patInst{op: "save", slot: 2 * n.group, x: body})
	case "repeat":
		body := n.children[0]
		if n.m < 0 {
			loop := p.loops
			p.loops++
			split := p.emit(patInst{op: "split"})
			p.scope = append(p.scope, loop)
			p.code[split].scope = append([]int(nil), p.scope...)
			guard := p.emit(patInst{op: "guard", slot: loop, x: split, y: next})
			start := p.compile(body, guard)
			mark := p.emit(patInst{op: "mark", slot: loop, x: start})
			p.scope = p.scope[:len(p.scope)-1]
			a, b := mark, next
			if n.lazy {
				a, b = b, a
			}
			p.code[split].x, p.code[split].y = a, b
			next = split
		} else {
			final := next
			for i := n.n; i < n.m; i++ {
				loop := p.loops
				p.loops++
				split := p.emit(patInst{op: "split"})
				p.scope = append(p.scope, loop)
				p.code[split].scope = append([]int(nil), p.scope...)
				guard := p.emit(patInst{op: "guard", slot: loop, x: next, y: final})
				start := p.compile(body, guard)
				mark := p.emit(patInst{op: "mark", slot: loop, x: start})
				p.scope = p.scope[:len(p.scope)-1]
				a, b := mark, final
				if n.lazy {
					a, b = b, a
				}
				p.code[split].x, p.code[split].y = a, b
				next = split
			}
		}
		for i := 0; i < n.n; i++ {
			next = p.compile(body, next)
		}
		return next
	}
	return p.emit(patInst{op: n.op, x: next, ranges: n.ranges, neg: n.neg})
}
func prim_pat_compile(s Value) Value {
	parser := patParser{s: []rune(s.(string))}
	n := parser.alt()
	if parser.peek() != -1 {
		patBad(parser.i, "unexpected parenthesis")
	}
	p := &Pat{groups: parser.groups}
	end := p.emit(patInst{op: "match"})
	end = p.emit(patInst{op: "save", slot: 1, x: end})
	body := p.compile(n, end)
	p.start = p.emit(patInst{op: "save", slot: 0, x: body})
	return p
}
func safe_pat_compile(s Value, site int) (result Value) {
	defer func() {
		if r := recover(); r != nil {
			if f, ok := r.(*Fail); ok && f.ID == "pat.BadPattern" {
				fault("E-PROOF-VIOLATED", site, "discharged operation at "+sites[site].Path+" violated", "")
			}
			panic(r)
		}
	}()
	return prim_pat_compile(s)
}
