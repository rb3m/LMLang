// Ordered Pike VM: Unicode scalars, first thread at each pc wins (ADR-075).
package main

import "strings"

type patThread struct {
	pc    int
	caps  []int
	marks map[int]int
}
type patList struct {
	threads []patThread
	seen    map[patState]bool
}
type patState struct{ pc, entered int }

func patCopy(xs []int) []int { return append([]int(nil), xs...) }
func patCopyMarks(marks map[int]int) map[int]int {
	out := make(map[int]int, len(marks))
	for loop, pos := range marks {
		out[loop] = pos
	}
	return out
}
func (p *Pat) add(l *patList, t patThread, pos, end int) {
	stack := []patThread{t}
	for len(stack) > 0 {
		t = stack[len(stack)-1]
		stack = stack[:len(stack)-1]
		i := p.code[t.pc]
		key := patState{t.pc, -1}
		if i.op != "class" && i.op != "dot" && i.op != "match" {
			key.entered = 0
			for _, loop := range i.scope {
				if marked, ok := t.marks[loop]; ok && marked == pos {
					key.entered++
				}
			}
		}
		if l.seen[key] {
			continue
		}
		l.seen[key] = true
		switch i.op {
		case "split":
			other := patThread{i.y, patCopy(t.caps), patCopyMarks(t.marks)}
			stack = append(stack, other)
			t.pc = i.x
		case "save":
			t.caps[i.slot] = pos
			t.pc = i.x
		case "mark":
			marks := make(map[int]int, len(i.scope))
			for _, loop := range i.scope {
				if marked, ok := t.marks[loop]; ok {
					marks[loop] = marked
				}
			}
			t.marks = marks
			t.marks[i.slot] = pos
			t.pc = i.x
		case "guard":
			t.pc = i.x
			if t.marks[i.slot] == pos {
				t.pc = i.y
			}
		case "start":
			if pos != 0 {
				continue
			}
			t.pc = i.x
		case "end":
			if pos != end {
				continue
			}
			t.pc = i.x
		default:
			l.threads = append(l.threads, t)
			continue
		}
		stack = append(stack, t)
	}
}
func (p *Pat) fresh() patThread {
	caps := make([]int, 2*(p.groups+1))
	for i := range caps {
		caps[i] = -1
	}
	return patThread{p.start, caps, make(map[int]int)}
}
func (p *Pat) search(text []rune, start int, whole bool) []int {
	cur := patList{seen: make(map[patState]bool)}
	var best []int
	for pos := start; pos <= len(text); pos++ {
		if best == nil && (!whole || pos == start) {
			p.add(&cur, p.fresh(), pos, len(text))
		}
		next := patList{seen: make(map[patState]bool)}
		for _, t := range cur.threads {
			i := p.code[t.pc]
			if i.op == "match" {
				if !whole || pos == len(text) {
					best = t.caps
					break
				}
				continue
			}
			if pos == len(text) {
				continue
			}
			ok := i.op == "dot" && text[pos] != '\n'
			if i.op == "class" {
				for _, r := range i.ranges {
					if text[pos] >= r.lo && text[pos] <= r.hi {
						ok = true
						break
					}
				}
				if i.neg {
					ok = !ok
				}
			}
			if ok {
				t.pc = i.x
				p.add(&next, t, pos+1, len(text))
			}
		}
		if best != nil && len(next.threads) == 0 {
			return best
		}
		cur = next
	}
	return best
}

var patMatchType = &RecType{"pat.Match", []string{"start", "end", "text", "groups"}}

func patMatch(text []rune, caps []int) Value {
	groups := make([]Value, len(caps)/2-1)
	for i := range groups {
		a, b := caps[2*i+2], caps[2*i+3]
		groups[i] = V_None
		if a >= 0 && b >= a {
			groups[i] = mkSome(string(text[a:b]))
		}
	}
	return &Record{patMatchType, []Value{int64(caps[0]), int64(caps[1]), string(text[caps[0]:caps[1]]), groups}}
}
func prim_pat_matches(s, pattern Value) Value {
	return pattern.(*Pat).search([]rune(s.(string)), 0, true) != nil
}
func prim_pat_find(s, pattern Value) Value {
	text := []rune(s.(string))
	caps := pattern.(*Pat).search(text, 0, false)
	if caps == nil {
		return V_None
	}
	return mkSome(patMatch(text, caps))
}
func patEach(text []rune, p *Pat, f func([]int)) {
	for pos := 0; pos <= len(text); {
		caps := p.search(text, pos, false)
		if caps == nil {
			return
		}
		f(caps)
		pos = caps[1]
		if caps[0] == caps[1] {
			pos++
		}
	}
}
func prim_pat_find_all(s, pattern Value) Value {
	text := []rune(s.(string))
	out := []Value{}
	patEach(text, pattern.(*Pat), func(caps []int) { out = append(out, patMatch(text, caps)) })
	return out
}
func prim_pat_split(s, pattern Value) Value {
	text := []rune(s.(string))
	out := []Value{}
	last := 0
	patEach(text, pattern.(*Pat), func(caps []int) {
		out = append(out, string(text[last:caps[0]]))
		last = caps[1]
	})
	return append(out, string(text[last:]))
}
func patReplace(s, pattern Value, replacement func(Value) string) Value {
	text := []rune(s.(string))
	var out strings.Builder
	last := 0
	patEach(text, pattern.(*Pat), func(caps []int) {
		out.WriteString(string(text[last:caps[0]]))
		out.WriteString(replacement(patMatch(text, caps)))
		last = caps[1]
	})
	out.WriteString(string(text[last:]))
	return out.String()
}
func prim_pat_replace_all(s, pattern, replacement Value) Value {
	return patReplace(s, pattern, func(_ Value) string { return replacement.(string) })
}
func prim_pat_replace_with(s, pattern, f Value) Value {
	return patReplace(s, pattern, func(m Value) string { return call1(f, m).(string) })
}
