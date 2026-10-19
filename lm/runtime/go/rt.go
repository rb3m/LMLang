// LM runtime for the Go backend: failures, faults, checked Int arithmetic, calls, output, entry.
// Outcomes follow ADR-031: success exit 0 (or the returned status), uncaught LM failure prints
// `(fail Err args..)` on stderr and exits 1, a fault prints one JSON diagnostic on stderr and exits 70.
package main

import (
	"bufio"
	"encoding/json"
	"fmt"
	"math"
	"os"
	"regexp"
	"runtime"
	"runtime/debug"
	"strconv"
	"strings"
)

// Site locates a node for fault diagnostics; generated code fills `sites` and passes indexes.
type Site struct {
	File      string
	Line, Col int
	Path, Fn  string
}

var sites []Site

// maxDepth bounds LM call depth so runaway recursion is the fault E-RECURSION-LIMIT instead of a
// fatal Go stack overflow; maxStack is the goroutine stack ceiling that depth needs (ADR-035).
const (
	maxDepth = 1000000
	maxStack = 8 << 30
)

var depth int

// Fail is a recoverable LM error value (`fail`), caught by `try` with a matching id.
type Fail struct {
	ID   string
	Args []Value
}

func (f *Fail) String() string {
	s := "(fail " + f.ID
	for _, a := range f.Args {
		s += " " + show(a)
	}
	return s + ")"
}

// Fault is an unrecoverable runtime fault; it carries the diagnostic printed on stderr.
type Fault struct{ D Diag }

type Diag struct {
	Code     string `json:"code"`
	Severity string `json:"severity"`
	File     string `json:"file"`
	Line     int    `json:"line"`
	Col      int    `json:"col"`
	Path     string `json:"path"`
	Msg      string `json:"msg"`
	Expected string `json:"expected"`
	Found    string `json:"found"`
	Fix      []any         `json:"fix"`
	Data     *OverflowData `json:"data,omitempty"`
}

func lmFail(id string, args ...Value) Value { panic(&Fail{id, args}) }

func fault(code string, site int, msg, found string) {
	d := Diag{Code: code, Severity: "error", Msg: msg, Found: found, Fix: []any{}}
	if site >= 0 {
		s := sites[site]
		d.File, d.Line, d.Col, d.Path = s.File, s.Line, s.Col, s.Path
	}
	panic(&Fault{d})
}

func enter() {
	depth++
	if depth > maxDepth {
		depth = 0
		fault("E-RECURSION-LIMIT", -1, "recursion limit reached ("+strconv.Itoa(maxDepth)+" nested calls)", "")
	}
}

func violation(code string, site int, args ...Value) {
	s := sites[site]
	clause := "requires"
	if code == "E-ENSURES-VIOLATED" {
		clause = "ensures"
	}
	fault(code, site, clause+" of "+s.Fn+" is false for arguments "+showArgs(args), showArgs(args))
}

// ---- checked 64-bit Int arithmetic (ADR-029/030: overflow is the fault E-OVERFLOW) -------------

const (
	guidance      = "Fix the arithmetic, validate input, or add a justified precondition; overflow cannot be caught."
	floatGuidance = "Fix the arithmetic, validate input, or add a justified precondition; a non-finite Float cannot be caught."
)

// OverflowData mirrors the interpreter's E-OVERFLOW/E-FLOAT `data` (lm/fault.py, ADR-030 item 5).
// Operands and bounds are int64 (E-OVERFLOW) or float64 (E-FLOAT; float.* conversions to Int give
// E-OVERFLOW with a float64 operand).
type OverflowData struct {
	Op            string   `json:"op"`
	Operands      []Value  `json:"operands"`
	Bounds        [2]Value `json:"bounds"`
	Frames        []string `json:"frames"`
	FramesOmitted int      `json:"frames_omitted"`
	UserPath      string   `json:"user_path"`
	Replay        string   `json:"replay"`
}

var stdlibMods map[string]bool

var liftedName = regexp.MustCompile(`^L[0-9]+_(.*)$`)

// demangle turns `list_X_index_of` back into `list.index-of` (inverse of gobackend.mangle).
func demangle(s string) string {
	mod, name, _ := strings.Cut(s, "_X_")
	return strings.ReplaceAll(mod, "_", "-") + "." + strings.ReplaceAll(name, "_", "-")
}

// lmFrames names the LM frames on the Go call stack, innermost first, as the interpreter does:
// `mod.fn` for functions (F_*) and `(lam) in mod.fn` for lambdas (lifted to L<n>_*). It also returns
// the qualified name of the nearest user (non-stdlib) function.
func lmFrames() (names []string, user string) {
	pcs := make([]uintptr, 256)
	for {
		n := runtime.Callers(3, pcs)
		if n < len(pcs) {
			pcs = pcs[:n]
			break
		}
		pcs = make([]uintptr, 2*len(pcs))
	}
	frames := runtime.CallersFrames(pcs)
	for {
		fr, more := frames.Next()
		fn := strings.TrimPrefix(fr.Function, "main.")
		if strings.HasPrefix(fn, "F_") && !strings.Contains(fn, ".") {
			q := demangle(fn[2:])
			names = append(names, q)
			mod, _, _ := strings.Cut(q, ".")
			if user == "" && !stdlibMods[mod] {
				user = q
			}
		} else if m := liftedName.FindStringSubmatch(fn); m != nil && !strings.Contains(fn, ".") {
			names = append(names, "(lam) in "+demangle(m[1]))
		}
		if !more {
			break
		}
	}
	return names, user
}

// pickFrames keeps at most 3 names, innermost first, keeping the nearest user frame visible.
func pickFrames(names []string, user string) []string {
	if len(names) <= 3 {
		return names
	}
	for k, n := range names {
		if n == user {
			if k < 3 {
				break
			}
			return append(append([]string{}, names[:2]...), n)
		}
	}
	return names[:3]
}

func overflow(op string, a, b int64, site int) {
	numFault("E-OVERFLOW", op, []Value{a, b}, site, site < 0)
}

// numFault reports E-OVERFLOW or E-FLOAT (same shape, ADR-039 item 4). site < 0: no node is known,
// either a prelude operator called back by a prim (`callback`) or a prim's own check.
func numFault(code, op string, operands []Value, site int, callback bool) {
	names, user := lmFrames()
	if callback { // a prelude operator called back by a prim (`+` passed to list.fold)
		names = append([]string{"`" + op + "` (callback)"}, names...)
	}
	shown := pickFrames(names, user)
	where := "top level"
	if len(shown) > 0 {
		where = strings.Join(shown, " <- ")
	}
	expr := "(" + op
	for _, a := range operands {
		expr += " " + show(a)
	}
	expr += ")"
	replay := "unavailable (compiled binary)"
	lead, bounds, guide := "Int overflow", [2]Value{int64(math.MinInt64), int64(math.MaxInt64)}, guidance
	if code == "E-FLOAT" {
		lead, bounds, guide = "Float result not finite", [2]Value{-math.MaxFloat64, math.MaxFloat64}, floatGuidance
	}
	d := Diag{Code: code, Severity: "error", Line: 1, Col: 1, Found: expr, Fix: []any{}}
	if site >= 0 {
		s := sites[site]
		d.File, d.Line, d.Col, d.Path = s.File, s.Line, s.Col, s.Path
	} else if user != "" { // the call site inside the user frame is not tracked; name the function
		mod, name, _ := strings.Cut(user, ".")
		d.Path = mod + "/" + name + "/body"
	}
	d.Msg = fmt.Sprintf("%s: %s is outside [%s, %s] in %s; replay: %s. %s",
		lead, expr, show(bounds[0]), show(bounds[1]), where, replay, guide)
	d.Data = &OverflowData{op, operands, bounds, shown, len(names) - len(shown), d.Path, replay}
	panic(&Fault{d})
}

func add(x, y Value, site int) Value {
	if f, ok := x.(float64); ok {
		return farith("+", f, y.(float64), site)
	}
	a, b := x.(int64), y.(int64)
	c := a + b
	if (a^c)&(b^c) < 0 {
		overflow("+", a, b, site)
	}
	return c
}

func sub(x, y Value, site int) Value {
	if f, ok := x.(float64); ok {
		return farith("-", f, y.(float64), site)
	}
	a, b := x.(int64), y.(int64)
	c := a - b
	if (a^b)&(a^c) < 0 {
		overflow("-", a, b, site)
	}
	return c
}

func mul(x, y Value, site int) Value {
	if f, ok := x.(float64); ok {
		return farith("*", f, y.(float64), site)
	}
	a, b := x.(int64), y.(int64)
	if a == 0 || b == 0 {
		return int64(0)
	}
	c := a * b
	if c/b != a || (a == -1 && b == math.MinInt64) || (b == -1 && a == math.MinInt64) {
		overflow("*", a, b, site)
	}
	return c
}

// Int div and mod use floor semantics and fail DivZero on a zero divisor (SPEC section 7); Float
// operands go to farith (float.go).
func div(x, y Value, site int) Value {
	if f, ok := x.(float64); ok {
		return farith("/", f, y.(float64), site)
	}
	a, b := x.(int64), y.(int64)
	if b == 0 {
		lmFail("DivZero")
	}
	if a == math.MinInt64 && b == -1 {
		overflow("/", a, b, site)
	}
	q := a / b
	if a%b != 0 && (a < 0) != (b < 0) {
		q--
	}
	return q
}

func mod(x, y Value, site int) Value {
	a, b := x.(int64), y.(int64)
	if b == 0 {
		lmFail("DivZero")
	}
	r := a % b
	if r != 0 && (r < 0) != (b < 0) {
		r += b
	}
	return r
}

func safe_div(x, y Value, site int) Value {
	if f, ok := x.(float64); ok {
		return farith("/", f, y.(float64), site)
	}
	a, b := x.(int64), y.(int64)
	if b == 0 {
		s := sites[site]
		fault("E-PROOF-VIOLATED", site, "discharged operation at "+s.Path+" violated", "")
	}
	if a == math.MinInt64 && b == -1 {
		overflow("/", a, b, site)
	}
	q := a / b
	if a%b != 0 && (a < 0) != (b < 0) {
		q--
	}
	return q
}

func safe_mod(x, y Value, site int) Value {
	a, b := x.(int64), y.(int64)
	if b == 0 {
		s := sites[site]
		fault("E-PROOF-VIOLATED", site, "discharged operation at "+s.Path+" violated", "")
	}
	r := a % b
	if r != 0 && (r < 0) != (b < 0) {
		r += b
	}
	return r
}

func cons(x, xs Value) Value {
	l := xs.([]Value)
	out := make([]Value, len(l)+1)
	out[0] = x
	copy(out[1:], l)
	return out
}

// ---- function values ------------------------------------------------------------------------------

func call1(f Value, a Value) Value {
	c := f.(*Closure)
	if c.F1 != nil {
		return c.F1(a)
	}
	return c.FN([]Value{a})
}

func call2(f Value, a, b Value) Value {
	c := f.(*Closure)
	if c.F2 != nil {
		return c.F2(a, b)
	}
	return c.FN([]Value{a, b})
}

func callN(f Value, args ...Value) Value {
	c := f.(*Closure)
	switch {
	case len(args) == 1 && c.F1 != nil:
		return c.F1(args[0])
	case len(args) == 2 && c.F2 != nil:
		return c.F2(args[0], args[1])
	}
	return c.FN(args)
}

// preludeValues holds the prelude operators usable as function values (`/` and `mod` are not).
var preludeValues = map[string]Value{
	"+":    &Closure{F2: func(a, b Value) Value { return add(a, b, -1) }},
	"-":    &Closure{F2: func(a, b Value) Value { return sub(a, b, -1) }},
	"*":    &Closure{F2: func(a, b Value) Value { return mul(a, b, -1) }},
	"=":    &Closure{F2: func(a, b Value) Value { return equal(a, b) }},
	"!=":   &Closure{F2: func(a, b Value) Value { return !equal(a, b) }},
	"<":    &Closure{F2: func(a, b Value) Value { return less(a, b) }},
	"<=":   &Closure{F2: func(a, b Value) Value { return !less(b, a) }},
	">":    &Closure{F2: func(a, b Value) Value { return less(b, a) }},
	">=":   &Closure{F2: func(a, b Value) Value { return !less(a, b) }},
	"cons": &Closure{F2: cons},
	"pair": &Closure{F2: makePair},
	"not":  &Closure{F1: func(a Value) Value { return !a.(bool) }},
	"len":  &Closure{F1: func(a Value) Value { return int64(len(a.([]Value))) }},
}

// ---- output ---------------------------------------------------------------------------------------

// out is stdout: line-buffered on a terminal, block-buffered otherwise; flushed at exit, before a
// fault or failure report, and (for I/O prims) before reading stdin. progArgs feeds `io.args`.
var (
	out      = bufio.NewWriterSize(os.Stdout, 65536)
	outTTY   = isTTY(os.Stdout)
	progArgs = cleanArgs(os.Args[1:])
)

func isTTY(f *os.File) bool {
	st, err := f.Stat()
	return err == nil && st.Mode()&os.ModeCharDevice != 0
}

func writeLine(s string) {
	out.WriteString(s)
	out.WriteByte('\n')
	if outTTY {
		out.Flush()
	}
}

// ---- entry points ------------------------------------------------------------------------------------

// outcome runs f and classifies the result: ("ok", value), ("fail", *Fail) or ("fault", *Fault).
// Any other panic is a toolchain bug and propagates (Go exits 2 with a stack trace).
func outcome(f func() Value) (kind string, v Value, fl *Fail, ft *Fault) {
	defer func() {
		if r := recover(); r != nil {
			depth = 0
			switch x := r.(type) {
			case *Fail:
				kind, fl = "fail", x
			case *Fault:
				kind, ft = "fault", x
			default:
				panic(r)
			}
		}
	}()
	return "ok", f(), nil, nil
}

func printFault(ft *Fault) {
	enc := json.NewEncoder(os.Stderr)
	enc.SetEscapeHTML(false)
	enc.Encode(ft.D)
}

// setup raises the stack ceiling and, unless GOGC is set, the GC target: LM programs allocate many
// short-lived boxed values and a small live heap, where Go's default (100) spends most time in GC.
func setup() {
	debug.SetMaxStack(maxStack)
	if os.Getenv("GOGC") == "" {
		debug.SetGCPercent(400)
	}
}

// runMain is the binary entry (ADR-031): Unit exits 0, Int is the exit status (0-255).
func runMain(entry func() Value, site int) {
	seedFromEnv()
	setup()
	kind, v, fl, ft := outcome(func() Value {
		r := entry()
		if n, ok := r.(int64); ok && (n < 0 || n > 255) {
			fault("E-EXIT-RANGE", site, "exit status "+strconv.FormatInt(n, 10)+" is outside 0-255", show(r))
		}
		return r
	})
	out.Flush()
	switch kind {
	case "fail":
		fmt.Fprintln(os.Stderr, fl.String())
		os.Exit(1)
	case "fault":
		printFault(ft)
		os.Exit(70)
	}
	if n, ok := v.(int64); ok {
		os.Exit(int(n))
	}
	os.Exit(0)
}

// Case is one example run by the differential harness (lm/build.py).
type Case struct {
	Label string
	Run   func() Value
}

// runCases prints `label<TAB>kind<TAB>detail` per case: ok + value, fail + (fail ..), fault + code.
func runCases(cases []Case) {
	setup()
	for _, c := range cases {
		randomState = 0
		kind, v, fl, ft := outcome(c.Run)
		detail := ""
		switch kind {
		case "ok":
			detail = show(v)
		case "fail":
			detail = fl.String()
		case "fault":
			detail = ft.D.Code
		}
		writeLine(c.Label + "\t" + kind + "\t" + detail)
	}
	out.Flush()
}
