package main

import (
	"encoding/hex"
	"encoding/json"
	"os"
	"sync"
	"time"
)

type hidReplayDevice struct {
	info     []Value
	attached bool
	queue    []hidReport
	features map[int64]Bytes
	handle   *hidDev
}

type hidReplay struct {
	mu       sync.Mutex
	stopping chan struct{}
	devices  []*hidReplayDevice
	byID     map[string]*hidReplayDevice
	events   []hidEvent
	opened   []*hidDev
	start    time.Time
	logPath  string
	logging  bool
}

func makeHidReplay(path string) hidAdapter {
	raw, err := os.ReadFile(path)
	if err != nil {
		return hidUnavailable{"io"}
	}
	trace, ok := parseHidTrace(raw)
	if !ok {
		return hidUnavailable{"io"}
	}
	log, logging := os.LookupEnv("LM_HID_REPLAY_LOG")
	r := &hidReplay{
		stopping: make(chan struct{}),
		byID:     map[string]*hidReplayDevice{}, events: trace.events,
		start: time.Now(), logPath: log, logging: logging,
	}
	for _, info := range trace.devices {
		d := &hidReplayDevice{info: info, attached: true, features: map[int64]Bytes{}}
		r.devices = append(r.devices, d)
		r.byID[info[0].(string)] = d
	}
	return r
}

func (r *hidReplay) now() int64 { return time.Since(r.start).Milliseconds() }

func (r *hidReplay) advance(through int64) {
	for len(r.events) > 0 && r.events[0].at <= through {
		event := r.events[0]
		r.events = r.events[1:]
		r.applyEvent(event)
	}
}

func (r *hidReplay) applyEvent(event hidEvent) {
	d := r.byID[event.device]
	if !d.attached {
		return
	}
	switch event.kind {
	case "unplug":
		d.attached = false
	case "report-id":
		if len(d.queue) == hidMaxQueue {
			d.queue = d.queue[1:]
		}
		d.queue = append(d.queue, event.report)
	case "feature-id":
		d.features[event.report.id] = event.report.data
	}
}

func (r *hidReplay) enumerate() [][]Value {
	rows := make([][]Value, 0, len(r.devices))
	for _, d := range r.devices {
		if d.attached {
			rows = append(rows, d.info)
		}
	}
	return rows
}

func (r *hidReplay) open(id string) *hidDev {
	d := r.byID[id]
	if d == nil || !d.attached {
		hidFail(id, "not-found")
	}
	if d.handle != nil {
		hidFail(id, "busy")
	}
	d.handle = &hidDev{id}
	r.opened = append(r.opened, d.handle)
	return d.handle
}

func (r *hidReplay) state(handle *hidDev, drain bool) *hidReplayDevice {
	d := r.byID[handle.id]
	if d == nil || d.handle != handle || (!drain && !d.attached) {
		hidFail(handle.id, "disconnected")
	}
	return d
}

func (r *hidReplay) read(handle *hidDev) Value {
	d := r.state(handle, true)
	if len(d.queue) > 0 {
		report := d.queue[0]
		d.queue[0] = hidReport{}
		d.queue = d.queue[1:]
		return report
	}
	if !d.attached {
		hidFail(handle.id, "disconnected")
	}
	return nil
}

func (r *hidReplay) log(op string, handle *hidDev, fields map[string]any) error {
	if !r.logging {
		return nil
	}
	if fields == nil {
		fields = map[string]any{}
	}
	fields["at-ms"], fields["op"], fields["dev"] = r.now(), op, handle.id
	stream, err := os.OpenFile(r.logPath, os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0666)
	if err != nil {
		return err
	}
	err = json.NewEncoder(stream).Encode(fields)
	closeErr := stream.Close()
	if err != nil {
		return err
	}
	return closeErr
}

func (r *hidReplay) record(op string, handle *hidDev, fields map[string]any) Value {
	if r.log(op, handle, fields) != nil {
		hidFail(handle.id, "io")
	}
	return U
}

func (r *hidReplay) send(op string, handle *hidDev, report hidReport) Value {
	r.state(handle, false)
	key := "report-id"
	if op == "feature-set" {
		key = "feature-id"
	}
	return r.record(op, handle, map[string]any{
		key: report.id, "data": hex.EncodeToString([]byte(report.data)),
	})
}

func (r *hidReplay) featureGet(handle *hidDev, id, length int64) Bytes {
	d := r.state(handle, false)
	r.record("feature-get", handle, map[string]any{"feature-id": id, "len": length})
	data, ok := d.features[id]
	if !ok {
		hidFail(handle.id, "not-found")
	}
	return data[:min(int64(len(data)), length)]
}

func hidReady(devices []*hidReplayDevice) []Value {
	ready := make([]Value, 0, len(devices))
	for i, d := range devices {
		if len(d.queue) > 0 || !d.attached {
			ready = append(ready, int64(i))
		}
	}
	return ready
}

func (r *hidReplay) wait(handles []Value, timeout int64) []Value {
	devices := make([]*hidReplayDevice, 0, len(handles))
	for _, handle := range handles {
		devices = append(devices, r.state(handle.(*hidDev), true))
	}
	deadline := r.now() + timeout
	for {
		now := r.now()
		r.advance(min(now, deadline))
		ready := hidReady(devices)
		if len(ready) > 0 || now >= deadline {
			return ready
		}
		wake := deadline
		if len(r.events) > 0 {
			wake = min(wake, r.events[0].at)
		}
		r.pause(wake - now)
	}
}

func (r *hidReplay) pause(ms int64) {
	timer := time.NewTimer(time.Duration(ms) * time.Millisecond)
	defer timer.Stop()
	select {
	case <-r.stopping:
		panic(hidInterrupted{})
	case <-timer.C:
	}
}

func (r *hidReplay) close(handle *hidDev) error {
	d := r.byID[handle.id]
	if d == nil || d.handle != handle {
		return nil
	}
	d.handle = nil
	for i, opened := range r.opened {
		if opened == handle {
			r.opened = append(r.opened[:i], r.opened[i+1:]...)
			break
		}
	}
	return r.log("close", handle, nil)
}

func (r *hidReplay) shutdown() {
	r.mu.Lock()
	defer r.mu.Unlock()
	for len(r.opened) > 0 {
		_ = r.close(r.opened[0])
	}
}

func (r *hidReplay) invoke(op string, args ...Value) Value {
	r.mu.Lock()
	defer r.mu.Unlock()
	select {
	case <-r.stopping:
		panic(hidInterrupted{})
	default:
	}
	r.advance(r.now())
	switch op {
	case "enumerate":
		return r.enumerate()
	case "open":
		return r.open(args[0].(string))
	case "read":
		return r.read(args[0].(*hidDev))
	case "write", "feature-set":
		return r.send(op, args[0].(*hidDev), args[1].(hidReport))
	case "feature-get":
		return r.featureGet(args[0].(*hidDev), args[1].(int64), args[2].(int64))
	case "grab":
		handle := args[0].(*hidDev)
		r.state(handle, false)
		return r.record(op, handle, map[string]any{"on": args[1]})
	case "wait":
		return r.wait(args[0].([]Value), args[1].(int64))
	case "close":
		handle := args[0].(*hidDev)
		if r.close(handle) != nil {
			hidFail(handle.id, "io")
		}
		return U
	case "supports":
		switch args[0] {
		case "enumerate", "read", "write", "feature", "grab":
			return true
		}
		return false
	}
	panic("unknown HID operation: " + op)
}
