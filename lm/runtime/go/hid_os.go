//go:build !darwin || !cgo

package main

import "time"

type hidUnsupported struct{ hidUnavailable }

func (a hidUnsupported) invoke(op string, args ...Value) Value {
	if op == "wait" && len(args[0].([]Value)) == 0 {
		timer := time.NewTimer(time.Duration(args[1].(int64)) * time.Millisecond)
		defer timer.Stop()
		select {
		case <-hidStopping:
			panic(hidInterrupted{})
		case <-timer.C:
			return []Value{}
		}
	}
	return a.hidUnavailable.invoke(op, args...)
}

func osHid() hidAdapter {
	return hidUnsupported{hidUnavailable{"unsupported"}}
}
