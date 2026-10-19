// LM runtime for the Go backend: stdlib `(prim "..")` bodies. THIS IS THE PLACE TO ADD A PRIM.
//
// One function per prim. The name is the prim name with `.` and `-` turned into `_`, prefixed
// with `prim_` ("str.index-of" -> prim_str_index_of). Parameters and result are Value, one
// parameter per LM parameter, in signature order. Use the LM representations from value.go
// (Int=int64, Str=string, List=[]Value, Unit=U, (Opt a)=mkSome(v)/V_None) and:
//   - lmFail("Err", args...) to raise a declared LM failure (e.g. OutOfRange, an I/O error);
//   - call1/call2/callN to call a function value argument;
//   - writeLine/out for stdout (call out.Flush() before reading stdin); progArgs for io.args.
// `lm build` checks that every prim reachable from the entry has a function here and names the
// missing one otherwise. The Python twin is lm/prims.py; tests/unit/test_gobackend.py compares them.
package main

import (
	"bufio"
	"errors"
	"io"
	"io/fs"
	"os"
	"strconv"
	"strings"
	"unicode/utf8"
)

func prim_list_concat(xs, ys Value) Value {
	a, b := xs.([]Value), ys.([]Value)
	out := make([]Value, 0, len(a)+len(b))
	return append(append(out, a...), b...)
}

func prim_list_filter(xs, keep Value) Value {
	out := []Value{}
	for _, x := range xs.([]Value) {
		if call1(keep, x).(bool) {
			out = append(out, x)
		}
	}
	return out
}

func prim_list_fold(xs, init, step Value) Value {
	acc := init
	for _, x := range xs.([]Value) {
		acc = call2(step, acc, x)
	}
	return acc
}

func prim_list_map(xs, f Value) Value {
	l := xs.([]Value)
	out := make([]Value, len(l))
	for i, x := range l {
		out[i] = call1(f, x)
	}
	return out
}

func prim_list_any(xs, pred Value) Value {
	for _, x := range xs.([]Value) {
		if call1(pred, x).(bool) {
			return true
		}
	}
	return false
}

func prim_list_all(xs, pred Value) Value {
	for _, x := range xs.([]Value) {
		if !call1(pred, x).(bool) {
			return false
		}
	}
	return true
}

func prim_list_map2(xs, ys, f Value) Value {
	a, b := xs.([]Value), ys.([]Value)
	n := min(len(a), len(b))
	out := make([]Value, n)
	for i := 0; i < n; i++ {
		out[i] = call2(f, a[i], b[i])
	}
	return out
}

func prim_list_index_of(xs, target Value) Value {
	for i, x := range xs.([]Value) {
		if equal(x, target) {
			return mkSome(int64(i))
		}
	}
	return V_None
}

func prim_list_nth(xs, i Value) Value {
	l, k := xs.([]Value), i.(int64)
	if k < 0 || k >= int64(len(l)) {
		lmFail("OutOfRange")
	}
	return l[k]
}

func safe_list_nth(xs, i Value, site int) Value {
	l, k := xs.([]Value), i.(int64)
	if k < 0 || k >= int64(len(l)) {
		s := sites[site]
		fault("E-PROOF-VIOLATED", site, "discharged operation at "+s.Path+" violated", "")
	}
	return l[k]
}

func prim_list_at(xs, i Value) Value {
	l, k := xs.([]Value), i.(int64)
	if k < 0 || k >= int64(len(l)) {
		return V_None
	}
	return mkSome(l[k])
}

// clampCount turns a take/drop count into 0..n (ADR-045).
func clampCount(k Value, n int) int { return int(max(0, min(k.(int64), int64(n)))) }

func prim_list_take(xs, n Value) Value {
	l := xs.([]Value)
	k := clampCount(n, len(l))
	return l[:k:k] // capacity k: an append elsewhere can never write into xs
}

func prim_list_drop(xs, n Value) Value {
	l := xs.([]Value)
	return l[clampCount(n, len(l)):]
}

// prim_list_sort_by is the stable top-down merge sort of lm/prims.py list_sort_by, step for step,
// so both backends call `less` in the same order and agree even for an inconsistent `less`.
func prim_list_sort_by(xs, less Value) Value {
	l := xs.([]Value)
	if len(l) <= 1 {
		return l
	}
	mid := len(l) / 2
	a, b := prim_list_sort_by(l[:mid], less).([]Value), prim_list_sort_by(l[mid:], less).([]Value)
	out := make([]Value, 0, len(l))
	i, j := 0, 0
	for i < len(a) && j < len(b) {
		if call2(less, b[j], a[i]).(bool) {
			out = append(out, b[j])
			j++
			continue
		}
		out = append(out, a[i])
		i++
	}
	return append(append(out, a[i:]...), b[j:]...)
}

func prim_list_range(start, stop Value) Value {
	a, b := start.(int64), stop.(int64)
	if b <= a {
		return []Value{}
	}
	out := make([]Value, 0, b-a)
	for i := a; i < b; i++ {
		out = append(out, i)
	}
	return out
}

func prim_list_reverse(xs Value) Value {
	l := xs.([]Value)
	out := make([]Value, len(l))
	for i, x := range l {
		out[len(l)-1-i] = x
	}
	return out
}

func prim_str_concat(a, b Value) Value { return a.(string) + b.(string) }

func prim_str_from_int(n Value) Value { return strconv.FormatInt(n.(int64), 10) }

func prim_str_join(parts, sep Value) Value {
	l := parts.([]Value)
	ss := make([]string, len(l))
	for i, p := range l {
		ss[i] = p.(string)
	}
	return strings.Join(ss, sep.(string))
}

func prim_str_length(s Value) Value { return int64(utf8.RuneCountInString(s.(string))) }

// ---- io (ADR-034): strict UTF-8, host error messages, failures io.IoError (msg) -----------------

var stdin = bufio.NewReaderSize(os.Stdin, 65536)

func prim_io_print(s Value) Value {
	writeLine(s.(string))
	return U
}

func prim_io_eprint(s Value) Value {
	out.Flush() // keep stdout and stderr in program order
	os.Stderr.WriteString(s.(string) + "\n")
	return U
}

func prim_io_args() Value {
	l := make([]Value, len(progArgs))
	for i, a := range progArgs {
		l[i] = a
	}
	return l
}

func ioFail(msg string) { lmFail("io.IoError", msg) }

func prim_io_read_line() Value {
	out.Flush()
	line, err := stdin.ReadString('\n')
	if err != nil && err != io.EOF {
		ioFail(err.Error())
	}
	if line == "" {
		return V_None
	}
	if !utf8.ValidString(line) {
		ioFail("invalid UTF-8 in input")
	}
	if strings.HasSuffix(line, "\n") {
		line = strings.TrimSuffix(strings.TrimSuffix(line, "\n"), "\r")
	}
	return mkSome(line)
}

func prim_io_read_all() Value {
	out.Flush()
	b, err := io.ReadAll(stdin)
	if err != nil {
		ioFail(err.Error())
	}
	if !utf8.Valid(b) {
		ioFail("invalid UTF-8 in input")
	}
	return string(b)
}

// ---- fs (ADR-034): failures fs.IoError (path, msg) ---------------------------------------------

func fsFail(path string, err error) { lmFail("fs.IoError", path, err.Error()) }

func prim_fs_read(path Value) Value {
	p := path.(string)
	b, err := os.ReadFile(p)
	if err != nil {
		fsFail(p, err)
	}
	if !utf8.Valid(b) {
		fsFail(p, errors.New("invalid UTF-8"))
	}
	return string(b)
}

func prim_fs_write(path, text Value) Value {
	p := path.(string)
	if err := os.WriteFile(p, []byte(text.(string)), 0o666); err != nil {
		fsFail(p, err)
	}
	return U
}

func prim_fs_exists(path Value) Value {
	p := path.(string)
	_, err := os.Stat(p)
	if err == nil {
		return true
	}
	if errors.Is(err, fs.ErrNotExist) {
		return false
	}
	fsFail(p, err)
	return false
}

// ---- str (ADR-034): offsets are Unicode characters ----------------------------------------------

func strList(parts []string) Value {
	l := make([]Value, len(parts))
	for i, p := range parts {
		l[i] = p
	}
	return l
}

func prim_str_split(s, sep Value) Value {
	if sep.(string) == "" && s.(string) == "" {
		return []Value{}
	}
	return strList(strings.Split(s.(string), sep.(string)))
}

// isTrimSpace matches the pinned LM whitespace set (ADR-063).
func isTrimSpace(r rune) bool {
	return (r >= 0x09 && r <= 0x0D) ||
		(r >= 0x1C && r <= 0x20) ||
		r == 0x85 || r == 0xA0 || r == 0x1680 ||
		(r >= 0x2000 && r <= 0x200A) ||
		r == 0x2028 || r == 0x2029 || r == 0x202F || r == 0x205F ||
		r == 0x3000
}

func prim_str_trim(s Value) Value { return strings.TrimFunc(s.(string), isTrimSpace) }

func prim_str_to_int(s Value) Value {
	t := s.(string)
	digits := strings.TrimLeft(t, "+-")
	if len(t)-len(digits) > 1 || digits == "" || strings.Trim(digits, "0123456789") != "" {
		return V_None
	}
	n, err := strconv.ParseInt(t, 10, 64)
	if err != nil {
		return V_None
	}
	return mkSome(n)
}

func prim_str_starts_with(s, prefix Value) Value { return strings.HasPrefix(s.(string), prefix.(string)) }

func prim_str_contains(s, part Value) Value { return strings.Contains(s.(string), part.(string)) }

func prim_str_substring(s, start, end Value) Value {
	r := []rune(s.(string))
	a, b := start.(int64), end.(int64)
	if a < 0 || a > b || b > int64(len(r)) {
		lmFail("OutOfRange")
	}
	return string(r[a:b])
}

func prim_str_lines(s Value) Value {
	t := s.(string)
	parts := []string{}
	for t != "" {
		i := strings.IndexAny(t, "\r\n")
		if i < 0 {
			parts = append(parts, t)
			break
		}
		parts = append(parts, t[:i])
		if strings.HasPrefix(t[i:], "\r\n") {
			i++
		}
		t = t[i+1:]
	}
	return strList(parts)
}
