// Virtual joystick state, validation and replay shared by the OS adapters.
package main

import (
	"fmt"
	"os"
	"slices"
	"sync"
	"time"
)

var vinputAxisCodes = map[string]uint16{
	"x": 0, "y": 1, "z": 2, "rx": 3, "ry": 4, "rz": 5,
	"throttle": 6, "rudder": 7, "wheel": 8, "gas": 9, "brake": 10,
}

type vinputAxis struct {
	Name string `json:"name"`
	Min  int64  `json:"min"`
	Max  int64  `json:"max"`
}

func (a vinputAxis) midpoint() int64 {
	// Floor the average without overflowing signed Int.
	return (a.Min & a.Max) + ((a.Min ^ a.Max) >> 1)
}

type vinputSpec struct {
	Name    string       `json:"name"`
	Vendor  int64        `json:"vendor"`
	Product int64        `json:"product"`
	Axes    []vinputAxis `json:"axes"`
	Buttons int64        `json:"buttons"`
	Hats    int64        `json:"hats"`
}

type vinputOutput interface {
	frame(*vinputDev, [][]any) string
	close() string
}

type vinputBackend interface {
	create(id string, spec vinputSpec) (vinputOutput, string)
}

type vinputControl[T comparable] struct{ pending, sent T }

type vinputDev struct {
	id      string
	spec    vinputSpec
	axes    []vinputControl[int64]
	buttons []vinputControl[bool]
	hats    []vinputControl[[2]int64]
	output  vinputOutput
}

func makeVinputDev(id string, spec vinputSpec, output vinputOutput) *vinputDev {
	dev := &vinputDev{id: id, spec: spec, output: output,
		axes:    make([]vinputControl[int64], len(spec.Axes)),
		buttons: make([]vinputControl[bool], spec.Buttons),
		hats:    make([]vinputControl[[2]int64], spec.Hats)}
	for i, axis := range spec.Axes {
		mid := axis.midpoint()
		dev.axes[i] = vinputControl[int64]{mid, mid}
	}
	return dev
}

func (d *vinputDev) changes() [][]any {
	events := make([][]any, 0)
	for i, control := range d.axes {
		if control.pending != control.sent {
			events = append(events, []any{"axis", d.spec.Axes[i].Name, control.pending})
		}
	}
	for i, control := range d.buttons {
		if control.pending != control.sent {
			events = append(events, []any{"button", i, control.pending})
		}
	}
	for i, control := range d.hats {
		if control.pending != control.sent {
			events = append(events, []any{"hat", i, control.pending[0], control.pending[1]})
		}
	}
	return events
}

func vinputCommit[T comparable](controls []vinputControl[T]) {
	for i := range controls {
		controls[i].sent = controls[i].pending
	}
}

func vinputFail(id, category string) {
	if category != "" {
		lmFail("vinput.VinputError", id, category)
	}
}

func readVinputSpec(value Value) vinputSpec {
	spec := vinputSpec{
		Name: getField(value, "name").(string), Vendor: getField(value, "vendor").(int64),
		Product: getField(value, "product").(int64), Buttons: getField(value, "buttons").(int64),
		Hats: getField(value, "hats").(int64),
	}
	axes := getField(value, "axes").([]Value)
	if len(spec.Name) == 0 || len(spec.Name) > 80 || spec.Vendor < 0 || spec.Vendor > 65535 ||
		spec.Product < 0 || spec.Product > 65535 || len(axes) > 16 ||
		spec.Buttons < 0 || spec.Buttons > 56 || spec.Hats < 0 || spec.Hats > 4 {
		vinputFail("", "invalid-request")
	}
	spec.Axes = make([]vinputAxis, 0, len(axes))
	seen := map[string]bool{}
	for _, value := range axes {
		axis := vinputAxis{getField(value, "name").(string),
			getField(value, "min").(int64), getField(value, "max").(int64)}
		_, known := vinputAxisCodes[axis.Name]
		if axis.Min >= axis.Max || !known || seen[axis.Name] {
			vinputFail("", "invalid-request")
		}
		seen[axis.Name] = true
		spec.Axes = append(spec.Axes, axis)
	}
	return spec
}

type vinputAdapter struct {
	mu      sync.Mutex
	backend vinputBackend
	now     func() int64
	opened  []*vinputDev
	nextID  int
	stopped bool
}

var vinputEnabled bool
var activeVinput *vinputAdapter

func startVinput() {
	if !vinputEnabled {
		return
	}
	a := &vinputAdapter{nextID: 1}
	if _, replay := os.LookupEnv("LM_HID_REPLAY"); !replay {
		a.backend = osVinput()
		activeVinput = a
		return
	}
	start := time.Now()
	a.now = func() int64 { return time.Since(start).Milliseconds() }
	if hid, ok := activeHid.(*hidReplay); ok {
		a.now = hid.now
	}
	a.backend = vinputRecorder{a.now}
	activeVinput = a
}

func closeVinput() {
	if activeVinput != nil {
		activeVinput.shutdown()
	}
}

func (a *vinputAdapter) shutdown() {
	a.mu.Lock()
	defer a.mu.Unlock()
	a.stopped = true
	for _, dev := range a.opened {
		_ = dev.output.close()
		dev.output = nil
	}
	a.opened = nil
}

func (a *vinputAdapter) create(value Value) Value {
	if a.stopped {
		vinputFail("", "disconnected")
	}
	if a.backend == nil {
		vinputFail("", "unsupported")
	}
	spec := readVinputSpec(value)
	id := fmt.Sprintf("v%d", a.nextID)
	output, category := a.backend.create(id, spec)
	vinputFail("", category)
	dev := makeVinputDev(id, spec, output)
	a.nextID++
	a.opened = append(a.opened, dev)
	return dev
}

func (a *vinputAdapter) close(dev *vinputDev) {
	if dev.output == nil {
		return
	}
	output := dev.output
	dev.output = nil
	i := slices.Index(a.opened, dev)
	a.opened = slices.Delete(a.opened, i, i+1)
	vinputFail(dev.id, output.close())
}

func (a *vinputAdapter) invoke(op string, args ...Value) Value {
	a.mu.Lock()
	defer a.mu.Unlock()
	switch op {
	case "supports":
		return !a.stopped && a.backend != nil && args[0] == "create"
	case "create":
		return a.create(args[0])
	case "close":
		a.close(args[0].(*vinputDev))
		return U
	}
	dev := args[0].(*vinputDev)
	if dev.output == nil {
		vinputFail(dev.id, "disconnected")
	}
	switch op {
	case "axis":
		dev.axis(args[1].(string), args[2].(int64))
	case "button":
		i := args[1].(int64)
		if i < 0 || i >= dev.spec.Buttons {
			vinputFail(dev.id, "invalid-request")
		}
		dev.buttons[i].pending = args[2].(bool)
	case "hat":
		i, x, y := args[1].(int64), args[2].(int64), args[3].(int64)
		if i < 0 || i >= dev.spec.Hats || x < -1 || x > 1 || y < -1 || y > 1 {
			vinputFail(dev.id, "invalid-request")
		}
		dev.hats[i].pending = [2]int64{x, y}
	case "sync":
		vinputFail(dev.id, dev.output.frame(dev, dev.changes()))
		vinputCommit(dev.axes)
		vinputCommit(dev.buttons)
		vinputCommit(dev.hats)
	}
	return U
}

func (d *vinputDev) axis(name string, value int64) {
	for i, axis := range d.spec.Axes {
		if axis.Name == name && axis.Min <= value && value <= axis.Max {
			d.axes[i].pending = value
			return
		}
	}
	vinputFail(d.id, "invalid-request")
}

type vinputRecorder struct{ now func() int64 }

type vinputRecordedJoystick struct {
	recorder vinputRecorder
	id       string
}

type vinputLogEntry struct {
	At  int64  `json:"at-ms"`
	Op  string `json:"op"`
	Dev string `json:"dev"`
}

func (r vinputRecorder) entry(op, id string) vinputLogEntry {
	return vinputLogEntry{r.now(), "vinput-" + op, id}
}

func vinputLog(row any) string {
	if path, logging := os.LookupEnv("LM_HID_REPLAY_LOG"); logging && appendReplayLog(path, row) != nil {
		return "io"
	}
	return ""
}

func (r vinputRecorder) create(id string, spec vinputSpec) (vinputOutput, string) {
	return vinputRecordedJoystick{r, id}, vinputLog(struct {
		vinputLogEntry
		vinputSpec
	}{r.entry("create", id), spec})
}

func (d vinputRecordedJoystick) frame(_ *vinputDev, events [][]any) string {
	return vinputLog(struct {
		vinputLogEntry
		Events [][]any `json:"events"`
	}{d.recorder.entry("frame", d.id), events})
}

func (d vinputRecordedJoystick) close() string {
	return vinputLog(d.recorder.entry("close", d.id))
}

func prim_vinput_create(spec Value) Value { return activeVinput.invoke("create", spec) }
func prim_vinput_axis(d, name, value Value) Value {
	return activeVinput.invoke("axis", d, name, value)
}
func prim_vinput_button(d, index, down Value) Value {
	return activeVinput.invoke("button", d, index, down)
}
func prim_vinput_hat(d, index, x, y Value) Value {
	return activeVinput.invoke("hat", d, index, x, y)
}
func prim_vinput_sync(d Value) Value       { return activeVinput.invoke("sync", d) }
func prim_vinput_close(d Value) Value      { return activeVinput.invoke("close", d) }
func prim_vinput_supports(cap Value) Value { return activeVinput.invoke("supports", cap) }
