package main

import (
	"os"
	"path/filepath"
	"testing"
)

func procTestOutcome(argv []Value, input string, cwd Value, env []Value) (value Value, category string) {
	defer func() {
		if failure := recover(); failure != nil {
			f, ok := failure.(*Fail)
			if !ok {
				panic(failure)
			}
			if f.ID != "proc.ProcError" || len(f.Args) != 1 {
				panic(failure)
			}
			category = f.Args[0].(string)
		}
	}()
	value = prim_proc_run(argv, input, cwd, env)
	return
}

func TestProcDirectExecution(t *testing.T) {
	if !procSupported {
		t.Skip("POSIX subprocesses unavailable")
	}
	argv := []Value{"/bin/sh", "-c", "printf out; printf err >&2; exit 7"}
	value, category := procTestOutcome(argv, "", V_None, []Value{})
	if category != "" || show(value) != `(new proc.Result (exit (proc.Exited 7)) (stdout "out") (stderr "err"))` {
		t.Fatalf("got %v / %s", value, category)
	}
	// Executable text without a shebang must not invoke any shell fallback.
	path := filepath.Join(t.TempDir(), "plain")
	if err := os.WriteFile(path, []byte("exit 0\n"), 0700); err != nil {
		t.Fatal(err)
	}
	_, category = procTestOutcome([]Value{path}, "", V_None, []Value{})
	if category != "spawn" {
		t.Fatalf("executable text returned %q, wanted spawn", category)
	}
}

func TestProcEmptyEnvironment(t *testing.T) {
	if !procSupported {
		t.Skip("POSIX subprocesses unavailable")
	}
	value, category := procTestOutcome([]Value{"/usr/bin/env"}, "", V_None, []Value{})
	if category != "" || getField(value, "stdout") != "" {
		t.Fatalf("empty environment inherited values: %v / %s", value, category)
	}
}

func TestProcEmptyCwdIsMissing(t *testing.T) {
	if !procSupported {
		t.Skip("POSIX subprocesses unavailable")
	}
	_, category := procTestOutcome([]Value{"/bin/sh", "-c", "exit 0"}, "", mkSome(""), []Value{})
	if category != "not-found" {
		t.Fatalf("empty cwd returned %q, wanted not-found", category)
	}
}
