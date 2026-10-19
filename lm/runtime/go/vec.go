// Persistent 32-way vector trie with a tail. Published nodes are never mutated.
package main

type vecNode [32]Value

type Vec struct {
	Count int
	Shift uint
	Root  *vecNode
	Tail  []Value
}

func vecEmpty() *Vec { return &Vec{0, 5, &vecNode{}, nil} }

// vecOf builds complete leaves bottom-up in linear time.
func vecOf(xs []Value) Value {
	v := vecEmpty()
	if len(xs) == 0 {
		return v
	}
	off := ((len(xs) - 1) >> 5) << 5
	v.Count, v.Tail = len(xs), append([]Value(nil), xs[off:]...)
	nodes := make([]*vecNode, 0, off/32)
	for i := 0; i < off; i += 32 {
		n := &vecNode{}
		copy(n[:], xs[i:i+32])
		nodes = append(nodes, n)
	}
	for len(nodes) > 32 {
		parents := make([]*vecNode, 0, (len(nodes)+31)/32)
		for i := 0; i < len(nodes); i += 32 {
			n := &vecNode{}
			for j := i; j < len(nodes) && j < i+32; j++ {
				n[j-i] = nodes[j]
			}
			parents = append(parents, n)
		}
		nodes, v.Shift = parents, v.Shift+5
	}
	for i, n := range nodes {
		v.Root[i] = n
	}
	return v
}

func vecLeaf(v *Vec, i int) []Value {
	if i >= v.Count-len(v.Tail) {
		return v.Tail
	}
	n := v.Root
	for level := v.Shift; level > 0; level -= 5 {
		n = n[(i>>level)&31].(*vecNode)
	}
	return n[:]
}

func vecAt(v *Vec, i int) Value { return vecLeaf(v, i)[i&31] }

func vecAssoc(n *vecNode, level uint, i int, x Value) *vecNode {
	out := *n
	k := (i >> level) & 31
	if level == 0 {
		out[k] = x
		return &out
	}
	out[k] = vecAssoc(n[k].(*vecNode), level-5, i, x)
	return &out
}

func vecSet(v *Vec, i int, x Value) *Vec {
	out := *v
	if i >= v.Count-len(v.Tail) {
		out.Tail = append([]Value(nil), v.Tail...)
		out.Tail[i&31] = x
		return &out
	}
	out.Root = vecAssoc(v.Root, v.Shift, i, x)
	return &out
}

func vecPath(level uint, leaf *vecNode) *vecNode {
	if level == 0 {
		return leaf
	}
	n := &vecNode{}
	n[0] = vecPath(level-5, leaf)
	return n
}

func vecPushTail(level uint, parent, tail *vecNode, count int) *vecNode {
	out := *parent
	k := ((count - 1) >> level) & 31
	if level == 5 {
		out[k] = tail
		return &out
	}
	if parent[k] == nil {
		out[k] = vecPath(level-5, tail)
		return &out
	}
	out[k] = vecPushTail(level-5, parent[k].(*vecNode), tail, count)
	return &out
}

func vecPush(v *Vec, x Value) *Vec {
	out := *v
	out.Count++
	if len(v.Tail) < 32 {
		out.Tail = append(append([]Value(nil), v.Tail...), x)
		return &out
	}
	leaf := &vecNode{}
	copy(leaf[:], v.Tail)
	out.Tail = []Value{x}
	if (v.Count >> 5) > (1 << v.Shift) {
		out.Root = &vecNode{}
		out.Root[0], out.Root[1] = v.Root, vecPath(v.Shift, leaf)
		out.Shift += 5
		return &out
	}
	out.Root = vecPushTail(v.Shift, v.Root, leaf, v.Count)
	return &out
}

func vecPopTail(level uint, parent *vecNode, count int) *vecNode {
	k := ((count - 2) >> level) & 31
	if level > 5 {
		child := vecPopTail(level-5, parent[k].(*vecNode), count)
		if child == nil && k == 0 {
			return nil
		}
		out := *parent
		if child == nil {
			out[k] = nil
		} else {
			out[k] = child
		}
		return &out
	}
	if k == 0 {
		return nil
	}
	out := *parent
	out[k] = nil
	return &out
}

func vecPop(v *Vec) *Vec {
	if v.Count == 1 {
		return vecEmpty()
	}
	out := *v
	out.Count--
	if len(v.Tail) > 1 {
		out.Tail = v.Tail[:len(v.Tail)-1]
		return &out
	}
	out.Tail = vecLeaf(v, v.Count-2)
	out.Root = vecPopTail(v.Shift, v.Root, v.Count)
	if out.Root == nil {
		out.Root = &vecNode{}
	}
	if out.Shift > 5 && out.Root[1] == nil {
		out.Root = out.Root[0].(*vecNode)
		out.Shift -= 5
	}
	return &out
}

// Leaf traversal never performs indexed lookups.
func vecEach(v *Vec, f func(Value)) {
	var walk func(*vecNode, uint)
	walk = func(n *vecNode, level uint) {
		if level == 0 {
			for _, x := range n {
				f(x)
			}
			return
		}
		for _, child := range n {
			if child == nil {
				break
			}
			walk(child.(*vecNode), level-5)
		}
	}
	walk(v.Root, v.Shift)
	for _, x := range v.Tail {
		f(x)
	}
}

func equalVec(a, b *Vec) bool {
	if a.Count != b.Count {
		return false
	}
	// Collect leaf references, not elements; comparison stays linear and shape-independent.
	leaves := [][]Value{}
	var walk func(*vecNode, uint)
	walk = func(n *vecNode, level uint) {
		if level == 0 {
			leaves = append(leaves, n[:])
			return
		}
		for _, child := range n {
			if child == nil {
				break
			}
			walk(child.(*vecNode), level-5)
		}
	}
	walk(b.Root, b.Shift)
	leaves = append(leaves, b.Tail)
	leafi, offset, same := 0, 0, true
	vecEach(a, func(x Value) {
		for offset == len(leaves[leafi]) {
			leafi++
			offset = 0
		}
		if !equal(x, leaves[leafi][offset]) {
			same = false
		}
		offset++
	})
	return same
}

func vecValid(v *Vec, i int64) bool     { return i >= 0 && i < int64(v.Count) }
func prim_vec_empty() Value             { return vecEmpty() }
func prim_vec_from_list(xs Value) Value { return vecOf(xs.([]Value)) }
func prim_vec_to_list(v Value) Value {
	xs := make([]Value, 0, v.(*Vec).Count)
	vecEach(v.(*Vec), func(x Value) { xs = append(xs, x) })
	return xs
}
func prim_vec_size(v Value) Value { return int64(v.(*Vec).Count) }
func prim_vec_at(v, i Value) Value {
	if !vecValid(v.(*Vec), i.(int64)) {
		return V_None
	}
	return mkSome(vecAt(v.(*Vec), int(i.(int64))))
}
func prim_vec_set(v, i, x Value) Value {
	if !vecValid(v.(*Vec), i.(int64)) {
		return V_None
	}
	return mkSome(vecSet(v.(*Vec), int(i.(int64)), x))
}
func prim_vec_nth(v, i Value) Value {
	if !vecValid(v.(*Vec), i.(int64)) {
		lmFail("OutOfRange")
	}
	return vecAt(v.(*Vec), int(i.(int64)))
}
func prim_vec_put(v, i, x Value) Value {
	if !vecValid(v.(*Vec), i.(int64)) {
		lmFail("OutOfRange")
	}
	return vecSet(v.(*Vec), int(i.(int64)), x)
}
func safe_vec_nth(v, i Value, site int) Value {
	if !vecValid(v.(*Vec), i.(int64)) {
		fault("E-PROOF-VIOLATED", site, "discharged operation at "+sites[site].Path+" violated", "")
	}
	return vecAt(v.(*Vec), int(i.(int64)))
}
func safe_vec_put(v, i, x Value, site int) Value {
	if !vecValid(v.(*Vec), i.(int64)) {
		fault("E-PROOF-VIOLATED", site, "discharged operation at "+sites[site].Path+" violated", "")
	}
	return vecSet(v.(*Vec), int(i.(int64)), x)
}
func prim_vec_push(v, x Value) Value { return vecPush(v.(*Vec), x) }
func prim_vec_pop(v Value) Value {
	if v.(*Vec).Count == 0 {
		return V_None
	}
	return mkSome(vecPop(v.(*Vec)))
}
func prim_vec_last(v Value) Value {
	x := v.(*Vec)
	if x.Count == 0 {
		return V_None
	}
	return mkSome(x.Tail[len(x.Tail)-1])
}
func prim_vec_fold(v, init, step Value) Value {
	acc := init
	vecEach(v.(*Vec), func(x Value) { acc = call2(step, acc, x) })
	return acc
}
func prim_vec_map(v, f Value) Value {
	xs := make([]Value, 0, v.(*Vec).Count)
	vecEach(v.(*Vec), func(x Value) { xs = append(xs, call1(f, x)) })
	return vecOf(xs)
}
func prim_vec_repeat(n, x Value) Value {
	if n.(int64) <= 0 {
		return vecEmpty()
	}
	xs := make([]Value, int(n.(int64)))
	for i := range xs {
		xs[i] = x
	}
	return vecOf(xs)
}
func prim_vec_tabulate(n, f Value) Value {
	if n.(int64) <= 0 {
		return vecEmpty()
	}
	xs := make([]Value, int(n.(int64)))
	for i := range xs {
		xs[i] = call1(f, int64(i))
	}
	return vecOf(xs)
}
