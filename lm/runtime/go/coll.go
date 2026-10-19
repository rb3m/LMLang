// LM runtime for the Go backend: Map and Set values and their prims (ADR-049).
// A persistent AVL tree, step for step the algorithm of lm/tree.py; the Python prims are in
// lm/coll_prims.py. Semantics never depend on the tree's shape: equality and every traversal use
// ascending key order (Int and Float numerically, Str by code point = UTF-8 byte order, false < true).
package main

// Coll is an LM Map (Set false) or Set (Set true). Sets store U as every value.
type Coll struct {
	Root *node
	Set  bool
}

type node struct {
	K, V Value
	L, R *node
	H, N int // height, size
}

func height(n *node) int {
	if n == nil {
		return 0
	}
	return n.H
}

func size(n *node) int {
	if n == nil {
		return 0
	}
	return n.N
}

func mk(k, v Value, l, r *node) *node {
	return &node{k, v, l, r, 1 + max(height(l), height(r)), 1 + size(l) + size(r)}
}

// cmpKey orders two keys of the same LM type: -1, 0 or 1.
func cmpKey(a, b Value) int {
	lt := false
	switch x := a.(type) {
	case int64:
		y := b.(int64)
		if x == y {
			return 0
		}
		lt = x < y
	case float64:
		y := b.(float64)
		if x == y {
			return 0
		}
		lt = x < y
	case string:
		y := b.(string)
		if x == y {
			return 0
		}
		lt = x < y
	case bool:
		y := b.(bool)
		if x == y {
			return 0
		}
		lt = y
	}
	if lt {
		return -1
	}
	return 1
}

func balance(k, v Value, l, r *node) *node {
	hl, hr := height(l), height(r)
	if hl > hr+1 {
		if height(l.L) >= height(l.R) {
			return mk(l.K, l.V, l.L, mk(k, v, l.R, r))
		}
		lr := l.R
		return mk(lr.K, lr.V, mk(l.K, l.V, l.L, lr.L), mk(k, v, lr.R, r))
	}
	if hr > hl+1 {
		if height(r.R) >= height(r.L) {
			return mk(r.K, r.V, mk(k, v, l, r.L), r.R)
		}
		rl := r.L
		return mk(rl.K, rl.V, mk(k, v, l, rl.L), mk(r.K, r.V, rl.R, r.R))
	}
	return mk(k, v, l, r)
}

func insert(n *node, k, v Value) *node {
	if n == nil {
		return mk(k, v, nil, nil)
	}
	switch cmpKey(k, n.K) {
	case -1:
		return balance(n.K, n.V, insert(n.L, k, v), n.R)
	case 1:
		return balance(n.K, n.V, n.L, insert(n.R, k, v))
	}
	return mk(k, v, n.L, n.R)
}

func find(n *node, k Value) *node {
	for n != nil {
		switch cmpKey(k, n.K) {
		case -1:
			n = n.L
		case 1:
			n = n.R
		default:
			return n
		}
	}
	return nil
}

func removeMin(n *node) *node {
	if n.L == nil {
		return n.R
	}
	return balance(n.K, n.V, removeMin(n.L), n.R)
}

// remove deletes k, which must be present (callers test with find first).
func remove(n *node, k Value) *node {
	switch cmpKey(k, n.K) {
	case -1:
		return balance(n.K, n.V, remove(n.L, k), n.R)
	case 1:
		return balance(n.K, n.V, n.L, remove(n.R, k))
	}
	if n.L == nil {
		return n.R
	}
	if n.R == nil {
		return n.L
	}
	m := n.R
	for m.L != nil {
		m = m.L
	}
	return balance(m.K, m.V, n.L, removeMin(n.R))
}

// walk calls f on every binding in ascending key order.
func walk(n *node, f func(k, v Value)) {
	for n != nil {
		walk(n.L, f)
		f(n.K, n.V)
		n = n.R
	}
}

func entries(n *node) []*node {
	out := make([]*node, 0, size(n))
	var rec func(*node)
	rec = func(n *node) {
		for n != nil {
			rec(n.L)
			out = append(out, n)
			n = n.R
		}
	}
	rec(n)
	return out
}

func mapOf(keys, vals []Value) Value {
	var root *node
	for i, k := range keys {
		root = insert(root, k, vals[i])
	}
	return &Coll{root, false}
}

func setOf(keys []Value) Value {
	var root *node
	for _, k := range keys {
		root = insert(root, k, U)
	}
	return &Coll{root, true}
}

func equalColl(a, b *Coll) bool {
	if a.Set != b.Set || size(a.Root) != size(b.Root) {
		return false
	}
	x, y := entries(a.Root), entries(b.Root)
	for i := range x {
		if !equal(x[i].K, y[i].K) || !equal(x[i].V, y[i].V) {
			return false
		}
	}
	return true
}

func with(c Value, root *node) Value { return &Coll{root, c.(*Coll).Set} }

func root(c Value) *node { return c.(*Coll).Root }

func prim_map_put(m, k, v Value) Value { return with(m, insert(root(m), k, v)) }

func prim_map_at(m, k Value) Value {
	if n := find(root(m), k); n != nil {
		return mkSome(n.V)
	}
	return V_None
}

func prim_map_has(m, k Value) Value { return find(root(m), k) != nil }

func prim_map_remove(m, k Value) Value {
	if find(root(m), k) == nil {
		return m
	}
	return with(m, remove(root(m), k))
}

func prim_map_size(m Value) Value { return int64(size(root(m))) }

func prim_map_keys(m Value) Value {
	out := make([]Value, 0, size(root(m)))
	walk(root(m), func(k, _ Value) { out = append(out, k) })
	return out
}

func prim_map_values(m Value) Value {
	out := make([]Value, 0, size(root(m)))
	walk(root(m), func(_, v Value) { out = append(out, v) })
	return out
}

func prim_map_fold(m, init, step Value) Value {
	acc := init
	walk(root(m), func(k, v Value) { acc = callN(step, acc, k, v) })
	return acc
}

func prim_map_to_list(m Value) Value {
	var out []Value
	walk(root(m), func(k, v Value) {
		out = append(out, makePair(k, v))
	})
	return out
}

func prim_map_from_list(ps Value) Value {
	var r *node
	for _, p := range ps.([]Value) {
		pair := p.(*Pair)
		r = insert(r, pair.A, pair.B)
	}
	return &Coll{Root: r, Set: false}
}

func prim_set_add(s, x Value) Value { return prim_map_put(s, x, U) }

func prim_set_has(s, x Value) Value { return prim_map_has(s, x) }

func prim_set_remove(s, x Value) Value { return prim_map_remove(s, x) }

func prim_set_size(s Value) Value { return prim_map_size(s) }

func prim_set_to_list(s Value) Value { return prim_map_keys(s) }

func prim_set_fold(s, init, step Value) Value {
	acc := init
	walk(root(s), func(k, _ Value) { acc = call2(step, acc, k) })
	return acc
}

// prim_set_union inserts t's elements into s in ascending order (as lm/coll_prims.py does).
func prim_set_union(s, t Value) Value {
	r := root(s)
	walk(root(t), func(k, _ Value) { r = insert(r, k, U) })
	return with(s, r)
}

func keep(s, t Value, inside bool) Value {
	var r *node
	walk(root(s), func(k, _ Value) {
		if (find(root(t), k) != nil) == inside {
			r = insert(r, k, U)
		}
	})
	return with(s, r)
}

func prim_set_intersect(s, t Value) Value { return keep(s, t, true) }

func prim_set_diff(s, t Value) Value { return keep(s, t, false) }
