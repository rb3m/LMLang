// Bounded direct subprocesses; no shell, ambient environment or inherited fds.
package main

import (
	"bytes"
	"errors"
	"io"
	"os"
	"os/exec"
	"strings"
	"sync"
	"syscall"
	"time"
	"unicode/utf8"
)

const (
	procInputLimit   = 8 << 20
	procOutputLimit  = 8 << 20
	procRequestLimit = 64 << 10
	procTotalTimeout = 30 * time.Second
)

var (
	procResultType   = &RecType{"proc.Result", []string{"exit", "stdout", "stderr"}}
	procExitedCtor   = &Ctor{"proc.Exited"}
	procSignaledCtor = &Ctor{"proc.Signaled"}
	procLimitError   = errors.New("subprocess output limit")
)

func procFail(category string) { lmFail("proc.ProcError", category) }

func procRequest(argv, input, cwd, env Value) ([]string, string, []string) {
	args := make([]string, len(argv.([]Value)))
	for i, arg := range argv.([]Value) {
		args[i] = arg.(string)
	}
	if len(args) == 0 || !strings.HasPrefix(args[0], "/") {
		procFail("invalid-request")
	}
	dir := ""
	if option := cwd.(*Variant); option.C == C_Some {
		dir = option.Args[0].(string)
	}
	all := append(append([]string{}, args...), input.(string), dir)
	for _, entry := range env.([]Value) {
		p := entry.(*Pair)
		all = append(all, p.A.(string), p.B.(string))
	}
	for _, s := range all {
		if strings.ContainsRune(s, 0) {
			procFail("invalid-request")
		}
	}
	for _, entry := range env.([]Value) {
		name := entry.(*Pair).A.(string)
		if name == "" || strings.Contains(name, "=") {
			procFail("invalid-request")
		}
	}
	seen := map[string]bool{}
	childEnv := make([]string, 0, len(env.([]Value)))
	for _, entry := range env.([]Value) {
		p := entry.(*Pair)
		name := p.A.(string)
		if seen[name] {
			procFail("invalid-request")
		}
		seen[name] = true
		childEnv = append(childEnv, name+"="+p.B.(string))
	}
	if len(input.(string)) > procInputLimit {
		procFail("invalid-request")
	}
	size := 0
	for _, s := range append(append([]string{}, args...), childEnv...) {
		size += len(s)
	}
	if size > procRequestLimit {
		procFail("invalid-request")
	}
	return args, dir, childEnv
}

// One mutex makes the shared byte limit exact across both draining goroutines.
type procOutput struct {
	mu      sync.Mutex
	size    int
	buffers [2]bytes.Buffer
}

type procWriter struct {
	output *procOutput
	stream int
}

func (w procWriter) Write(p []byte) (int, error) {
	w.output.mu.Lock()
	defer w.output.mu.Unlock()
	if w.output.size+len(p) > procOutputLimit {
		return 0, procLimitError
	}
	w.output.size += len(p)
	return w.output.buffers[w.stream].Write(p)
}

func procClose(files []*os.File) {
	for _, f := range files {
		if f != nil {
			f.Close()
		}
	}
}

func prim_proc_run(argv, input, cwd, env Value) Value {
	args, dir, childEnv := procRequest(argv, input, cwd, env)
	if !procSupported {
		procFail("unsupported")
	}
	// Cmd.Dir == "" means no chdir, so preserve Some("") as a missing path.
	if cwd.(*Variant).C == C_Some && dir == "" {
		procFail("not-found")
	}
	deadline := time.Now().Add(procTotalTimeout)
	timer := time.NewTimer(time.Until(deadline))
	defer timer.Stop()
	// Each pipe has a parent endpoint and an endpoint closed after Start.
	files := make([]*os.File, 6)
	defer procClose(files)
	for i := 0; i < len(files); i += 2 {
		r, w, err := os.Pipe()
		if err != nil {
			procFail("io")
		}
		files[i], files[i+1] = r, w
	}
	cmd := &exec.Cmd{Path: args[0], Args: args, Dir: dir, Env: childEnv,
		Stdin: files[0], Stdout: files[3], Stderr: files[5]}
	procSetup(cmd)
	if err := cmd.Start(); err != nil {
		procFail(procStartCategory(err))
	}
	procClose([]*os.File{files[0], files[3], files[5]})
	copies := make(chan error, 3)
	go func() {
		_, err := io.Copy(files[1], strings.NewReader(input.(string)))
		if errors.Is(err, syscall.EPIPE) {
			err = nil
		}
		if closeErr := files[1].Close(); err == nil {
			err = closeErr
		}
		copies <- err
	}()
	output := &procOutput{}
	for stream, file := range []*os.File{files[2], files[4]} {
		go func(n int, f *os.File) {
			_, err := io.Copy(procWriter{output, n}, f)
			copies <- err
		}(stream, file)
	}
	waited := make(chan error, 1)
	go func() { waited <- cmd.Wait() }()
	pending, finished := 3, false
	var waitErr error
	category := ""
	for pending != 0 || !finished {
		select {
		case err := <-copies:
			pending--
			if err != nil && category == "" {
				category = "io"
				if errors.Is(err, procLimitError) {
					category = "limit"
				}
			}
		case waitErr = <-waited:
			finished = true
		case <-timer.C:
			if category == "" {
				category = "timeout"
			}
		}
		if category != "" {
			procKill(cmd)
			procClose([]*os.File{files[1], files[2], files[4]})
		}
	}
	// A ready completion channel must not win a select against an expired timer.
	if category == "" && !time.Now().Before(deadline) {
		procKill(cmd)
		category = "timeout"
	}
	if category != "" {
		procFail(category)
	}
	if waitErr != nil {
		var exited *exec.ExitError
		if !errors.As(waitErr, &exited) {
			procFail("io")
		}
	}
	out, errout := output.buffers[0].Bytes(), output.buffers[1].Bytes()
	if !utf8.Valid(out) || !utf8.Valid(errout) {
		procFail("invalid-utf8")
	}
	if !time.Now().Before(deadline) {
		procKill(cmd)
		procFail("timeout")
	}
	return &Record{procResultType, []Value{procExit(cmd.ProcessState), string(out), string(errout)}}
}
