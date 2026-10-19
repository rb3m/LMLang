// LM runtime for the Go backend: value representation, equality and LM-syntax printing.
// Copied verbatim next to the generated main.go by `lm build` (lm/gobackend.py); see ADR-035.
package main

import (
	"strconv"
	"strings"
)

// Value is any LM value. Int=int64, Float=float64 (finite, never -0.0), Bool=bool, Str=string, Unit=UnitT, List=[]Value,
// variants=*Variant, records=*Record, Map and Set=*Coll (coll.go), Vec=*Vec (vec.go), functions=*Closure.
type Value = any

type UnitT struct{}

var U Value = UnitT{}

type Ctor struct {
	Name string // as printed: "Some", "billing.Circle"
}

type Variant struct {
	C    *Ctor
	Args []Value
}

type RecType struct {
	Name   string   // qualified type name
	Fields []string // declaration order
}

type Record struct {
	T *RecType
	F []Value
}

type Pair struct {
	A Value
	B Value
}

func makePair(a, b Value) Value { return &Pair{A: a, B: b} }

func isPair(v Value) bool {
	_, ok := v.(*Pair)
	return ok
}

// Closure is a function value. F1/F2 are fast paths for arity 1 and 2; FN takes any arity.
type Closure struct {
	F1 func(Value) Value
	F2 func(Value, Value) Value
	FN func([]Value) Value
}

var (
	C_Some = &Ctor{"Some"}
	C_None = &Ctor{"None"}
	V_None = &Variant{C_None, nil}
)

func mkSome(v Value) Value { return &Variant{C_Some, []Value{v}} }

func variantArg(v Value, i int) Value { return v.(*Variant).Args[i] }

func hasTag(v Value, c *Ctor) bool { return v.(*Variant).C == c }

func getField(r Value, name string) Value {
	rec := r.(*Record)
	for i, f := range rec.T.Fields {
		if f == name {
			return rec.F[i]
		}
	}
	panic("no field " + name + " in " + rec.T.Name)
}

// withFields copies r and sets the given (name, value) pairs.
func withFields(r Value, pairs ...Value) Value {
	rec := r.(*Record)
	out := &Record{rec.T, append([]Value(nil), rec.F...)}
	for k := 0; k < len(pairs); k += 2 {
		name := pairs[k].(string)
		for i, f := range rec.T.Fields {
			if f == name {
				out.F[i] = pairs[k+1]
			}
		}
	}
	return out
}

// equal is LM structural, type-strict equality (`=`); function values compare by identity.
func equal(a, b Value) bool {
	switch x := a.(type) {
	case int64, float64, bool, string, UnitT: // Floats are finite and never -0.0 (ADR-039)
		return a == b
	case []Value:
		y := b.([]Value)
		if len(x) != len(y) {
			return false
		}
		for i := range x {
			if !equal(x[i], y[i]) {
				return false
			}
		}
		return true
	case *Variant:
		y := b.(*Variant)
		return x.C == y.C && equal([]Value(x.Args), []Value(y.Args))
	case *Record:
		y := b.(*Record)
		return x.T == y.T && equal([]Value(x.F), []Value(y.F))
	case *Pair:
		y, ok := b.(*Pair)
		return ok && equal(x.A, y.A) && equal(x.B, y.B)
	case *Coll:
		return equalColl(x, b.(*Coll))
	case *Vec:
		return equalVec(x, b.(*Vec))
	case *Closure:
		return x == b.(*Closure)
	}
	panic("equal: unknown value")
}

// less orders Ints and Floats numerically and Strs by code point (byte order of valid UTF-8).
func less(a, b Value) bool {
	if x, ok := a.(int64); ok {
		return x < b.(int64)
	}
	if x, ok := a.(float64); ok {
		return x < b.(float64)
	}
	return a.(string) < b.(string)
}

// show prints a value in LM syntax, identical to lm/values.py show().
func show(v Value) string {
	var b strings.Builder
	showTo(&b, v)
	return b.String()
}

func showTo(b *strings.Builder, v Value) {
	switch x := v.(type) {
	case int64:
		b.WriteString(strconv.FormatInt(x, 10))
	case float64:
		b.WriteString(showFloat(x))
	case bool:
		b.WriteString(strconv.FormatBool(x))
	case string:
		b.WriteByte('"')
		for _, r := range x {
			switch r {
			case '\\':
				b.WriteString("\\\\")
			case '"':
				b.WriteString("\\\"")
			case '\n':
				b.WriteString("\\n")
			case '\t':
				b.WriteString("\\t")
			default:
				if r < 0x20 || (r >= 0x7F && r <= 0x9F) {
					b.WriteString("\\u{")
					b.WriteString(strconv.FormatInt(int64(r), 16))
					b.WriteByte('}')
				} else {
					b.WriteRune(r)
				}
			}
		}
		b.WriteByte('"')
	case UnitT:
		b.WriteString("unit")
	case []Value:
		b.WriteString("(list")
		for _, e := range x {
			b.WriteByte(' ')
			showTo(b, e)
		}
		b.WriteByte(')')
	case *Variant:
		if len(x.Args) == 0 {
			b.WriteString(x.C.Name)
			return
		}
		b.WriteString("(" + x.C.Name)
		for _, e := range x.Args {
			b.WriteByte(' ')
			showTo(b, e)
		}
		b.WriteByte(')')
	case *Record:
		b.WriteString("(new " + x.T.Name)
		for i, f := range x.T.Fields {
			b.WriteString(" (" + f + " ")
			showTo(b, x.F[i])
			b.WriteByte(')')
		}
		b.WriteByte(')')
	case *Pair:
		b.WriteString("(pair ")
		showTo(b, x.A)
		b.WriteByte(' ')
		showTo(b, x.B)
		b.WriteByte(')')
	case *Coll:
		showColl(b, x)
	case *Vec:
		b.WriteString("(vecof")
		vecEach(x, func(e Value) { b.WriteByte(' '); showTo(b, e) })
		b.WriteByte(')')
	case *Pat:
		b.WriteString("<pat>")
	default:
		b.WriteString("<fn>")
	}
}

// showColl prints `(setof k..)` or `(mapof (k v)..)` in ascending key order, as values.py show_coll.
func showColl(b *strings.Builder, c *Coll) {
	if c.Set {
		b.WriteString("(setof")
	} else {
		b.WriteString("(mapof")
	}
	walk(c.Root, func(k, v Value) {
		b.WriteByte(' ')
		if c.Set {
			showTo(b, k)
			return
		}
		b.WriteByte('(')
		showTo(b, k)
		b.WriteByte(' ')
		showTo(b, v)
		b.WriteByte(')')
	})
	b.WriteByte(')')
}

// showArgs prints an argument tuple as `(a b c)`.
func showArgs(args []Value) string {
	parts := make([]string, len(args))
	for i, a := range args {
		parts[i] = show(a)
	}
	return "(" + strings.Join(parts, " ") + ")"
}
