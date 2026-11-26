// HID prim contract and startup selection. The OS choice is local to hid_os.go.
package main

import (
	"os"
	"os/signal"
)

const (
	hidMaxLength  = 4096
	hidMaxQueue   = 1024
	hidMaxTimeout = 3600000
)

type hidAdapter interface {
	invoke(op string, args ...Value) Value
	shutdown()
}

type hidDev struct{ id string }

type hidReport struct {
	id   int64
	data Bytes
}

type hidUnavailable struct{ category string }

func (a hidUnavailable) invoke(op string, args ...Value) Value {
	if op == "supports" {
		return false
	}
	id := ""
	if op == "open" {
		id = args[0].(string)
	}
	hidFail(id, a.category)
	return nil
}

func (hidUnavailable) shutdown() {}

var hidEnabled bool
var activeHid hidAdapter
var hidStopping = make(chan struct{})

func startHid() {
	if !hidEnabled {
		return
	}
	if path, ok := os.LookupEnv("LM_HID_REPLAY"); ok {
		activeHid = makeHidReplay(path)
		return
	}
	activeHid = osHid()
}

func closeHid() {
	if activeHid != nil {
		activeHid.shutdown()
	}
}

func stopHid() {
	closeHid()
	activeHid = nil
}

type hidInterrupted struct{}

func interruptHid() {
	close(hidStopping)
	if replay, ok := activeHid.(*hidReplay); ok {
		close(replay.stopping)
	}
}

func checkHidInterrupt() {
	select {
	case <-hidStopping:
		panic(hidInterrupted{})
	default:
	}
}

// Finish the replay log before exiting on a terminal interrupt.
func watchHidInterrupt() func() {
	replay, ok := activeHid.(*hidReplay)
	if !ok {
		return func() {}
	}
	signals := make(chan os.Signal, 1)
	done := make(chan struct{})
	signal.Notify(signals, os.Interrupt)
	go func() {
		select {
		case <-signals:
			close(replay.stopping)
			replay.shutdown()
			os.Exit(130)
		case <-done:
		}
	}()
	return func() {
		signal.Stop(signals)
		close(done)
	}
}

func hidFail(id, category string) { lmFail("hid.HidError", id, category) }

func hidReportID(n int64) bool { return n >= 0 && n <= 255 }
func hidLength(n int64) bool   { return n >= 1 && n <= hidMaxLength }

var hidInfoType = &RecType{"hid.Info", []string{
	"id", "vendor", "product", "usage-page", "usage", "interface", "name", "serial",
}}
var hidReportType = &RecType{"hid.Report", []string{"id", "data"}}

func prim_hid_enumerate() Value {
	rows := activeHid.invoke("enumerate").([][]Value)
	values := make([]Value, 0, len(rows))
	for _, row := range rows {
		values = append(values, &Record{hidInfoType, row})
	}
	return values
}

func prim_hid_open(id Value) Value { return activeHid.invoke("open", id) }

func prim_hid_read(handle Value) Value {
	report, ok := activeHid.invoke("read", handle).(hidReport)
	if !ok {
		return V_None
	}
	return mkSome(&Record{hidReportType, []Value{report.id, report.data}})
}

func hidSend(op string, handle, row Value) Value {
	id := getField(row, "id").(int64)
	data := getField(row, "data").(Bytes)
	if !hidReportID(id) || !hidLength(int64(len(data))) {
		hidFail(handle.(*hidDev).id, "invalid-request")
	}
	return activeHid.invoke(op, handle, hidReport{id, data})
}

func prim_hid_write(handle, row Value) Value { return hidSend("write", handle, row) }

func prim_hid_feature_set(handle, row Value) Value { return hidSend("feature-set", handle, row) }

func prim_hid_feature_get(handle, id, length Value) Value {
	if !hidReportID(id.(int64)) || !hidLength(length.(int64)) {
		hidFail(handle.(*hidDev).id, "invalid-request")
	}
	return activeHid.invoke("feature-get", handle, id, length)
}

func prim_hid_grab(handle, on Value) Value { return activeHid.invoke("grab", handle, on) }

func prim_hid_wait(handles, timeout Value) Value {
	if unavailable, ok := activeHid.(hidUnavailable); ok && unavailable.category == "io" {
		return activeHid.invoke("wait", handles, timeout)
	}
	ms := timeout.(int64)
	if ms < 0 || ms > hidMaxTimeout {
		hidFail("", "invalid-request")
	}
	return activeHid.invoke("wait", handles, timeout)
}

func prim_hid_close(handle Value) Value { return activeHid.invoke("close", handle) }

func prim_hid_supports(cap Value) Value { return activeHid.invoke("supports", cap) }
