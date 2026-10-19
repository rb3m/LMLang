//go:build !unix

package main

import (
	"os"
	"os/exec"
)

const procSupported = false

func procSetup(cmd *exec.Cmd)               {}
func procKill(cmd *exec.Cmd)                {}
func procStartCategory(err error) string    { return "unsupported" }
func procExit(state *os.ProcessState) Value { return nil }
