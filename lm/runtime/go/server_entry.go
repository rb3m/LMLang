// Built server startup: CGI unless --listen is explicitly selected.
package main

import (
	"bufio"
	"fmt"
	"os"
	"strconv"
	"sync"
)

func runServe(entry func(Value) Value, site int) {
	listen, public, host, port := false, false, "127.0.0.1", 8080
	args := os.Args[1:]
	for i := 0; i < len(args); i++ {
		switch args[i] {
		case "--listen":
			listen = true
		case "--public":
			public = true
		case "--host", "--port":
			flag := args[i]
			i++
			if i >= len(args) {
				fmt.Fprintln(os.Stderr, flag, "needs a value")
				os.Exit(2)
			}
			if flag == "--host" {
				host = args[i]
				continue
			}
			n, err := strconv.Atoi(args[i])
			if err != nil || n < 0 || n > 65535 {
				fmt.Fprintln(os.Stderr, "--port must be 0-65535")
				os.Exit(2)
			}
			port = n
		default:
			fmt.Fprintln(os.Stderr, "unknown server argument", args[i])
			os.Exit(2)
		}
	}
	if !listen && len(args) != 0 {
		fmt.Fprintln(os.Stderr, "listener options require --listen")
		os.Exit(2)
	}
	seedFromEnv()
	setup()
	// Handler io.print belongs on stderr; stdout is reserved for CGI protocol.
	out.writer = bufio.NewWriterSize(os.Stderr, 65536)
	outTTY = isTTY(os.Stderr)
	status := func() int {
		startDevices()
		if vinputEnabled {
			shutdown := sync.OnceFunc(closeDevices)
			defer watchRuntimeSignals(shutdown)()
			defer shutdown()
		}
		if !vinputEnabled {
			defer watchHidInterrupt()()
			defer stopDevices()
		}
		if !listen {
			serverCGI(entry)
			return 0
		}
		return serverListen(entry, host, port, public)
	}()
	os.Exit(status)
}
