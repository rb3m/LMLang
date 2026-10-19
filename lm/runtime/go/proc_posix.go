//go:build unix

package main

import (
	"errors"
	"os"
	"os/exec"
	"syscall"
)

const procSupported = true

func procSetup(cmd *exec.Cmd) { cmd.SysProcAttr = &syscall.SysProcAttr{Setpgid: true} }

func procKill(cmd *exec.Cmd) { syscall.Kill(-cmd.Process.Pid, syscall.SIGKILL) }

func procStartCategory(err error) string {
	if errors.Is(err, syscall.ENOENT) || errors.Is(err, syscall.ENOTDIR) {
		return "not-found"
	}
	if errors.Is(err, syscall.EACCES) || errors.Is(err, syscall.EPERM) {
		return "permission"
	}
	return "spawn"
}

func procExit(state *os.ProcessState) Value {
	status := state.Sys().(syscall.WaitStatus)
	if status.Signaled() {
		return &Variant{procSignaledCtor, []Value{int64(status.Signal())}}
	}
	return &Variant{procExitedCtor, []Value{int64(status.ExitStatus())}}
}
