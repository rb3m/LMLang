//go:build linux

package main

import (
	"errors"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"sync"
	"syscall"
	"time"
)

type linuxNode struct{ id, raw, device string }

type linuxDevice struct {
	fd           int
	path         string
	numbered     bool
	readonly     bool
	zeroPrefixed bool
	removed      bool
	grabs        []int
	queue        [hidMaxQueue]hidReport
	head         int
	count        int
}

func (d *linuxDevice) push(report hidReport) {
	d.queue[(d.head+d.count)%hidMaxQueue] = report
	if d.count == hidMaxQueue {
		d.head = (d.head + 1) % hidMaxQueue
		return
	}
	d.count++
}

func (d *linuxDevice) pop() hidReport {
	report := d.queue[d.head]
	d.queue[d.head] = hidReport{}
	d.head = (d.head + 1) % hidMaxQueue
	d.count--
	return report
}

type linuxHid struct {
	mu      sync.Mutex
	sysRoot string
	devRoot string
	devices map[*hidDev]*linuxDevice
	openIDs map[string]bool
}

func makeLinuxHid(sysRoot, devRoot string) *linuxHid {
	return &linuxHid{sysRoot: sysRoot, devRoot: devRoot,
		devices: make(map[*hidDev]*linuxDevice), openIDs: make(map[string]bool)}
}

func osHid() hidAdapter { return makeLinuxHid("/sys/class/hidraw", "/dev") }

func (a *linuxHid) scan(id string) []linuxNode {
	names, err := linuxChildren(a.sysRoot, "hidraw")
	if err != nil {
		hidFail(id, linuxError(err, false))
	}
	var nodes []linuxNode
	for _, name := range names {
		raw := filepath.Join(a.sysRoot, name, "device")
		device, err := filepath.EvalSymlinks(raw)
		if linuxMissing(err) {
			continue
		}
		if err != nil {
			hidFail(id, linuxError(err, false))
		}
		ident := "linux:" + strings.ToLower(filepath.Base(device))
		nodes = append(nodes, linuxNode{ident, name, device})
	}
	sort.Slice(nodes, func(i, j int) bool { return nodes[i].id < nodes[j].id })
	return nodes
}

func (a *linuxHid) enumerate() [][]Value {
	var rows [][]Value
	for _, node := range a.scan("") {
		_, vendor, product, name, serial := linuxUevent(node.device)
		descriptor, _ := os.ReadFile(filepath.Join(node.device, "report_descriptor"))
		page, usage, _ := linuxDescriptorInfo(descriptor)
		rows = append(rows, []Value{node.id, vendor, product, page, usage,
			linuxInterface(node.device), name, serial})
	}
	return rows
}

func (a *linuxHid) find(id string) linuxNode {
	for _, node := range a.scan(id) {
		if node.id == id {
			return node
		}
	}
	hidFail(id, "not-found")
	return linuxNode{}
}

func (a *linuxHid) open(id string) *hidDev {
	if a.openIDs[id] {
		hidFail(id, "busy")
	}
	node := a.find(id)
	descriptor, err := os.ReadFile(filepath.Join(node.device, "report_descriptor"))
	if err != nil {
		hidFail(id, linuxError(err, false))
	}
	bus, _, _, _, _ := linuxUevent(node.device)
	_, _, numbered := linuxDescriptorInfo(descriptor)
	fd, readonly, err := linuxOpenRaw(filepath.Join(a.devRoot, node.raw))
	if err != nil {
		hidFail(id, linuxError(err, false))
	}
	// Recheck the attachment in case the kernel reused hidrawN during open.
	device, err := filepath.EvalSymlinks(filepath.Join(a.sysRoot, node.raw, "device"))
	if err != nil || device != node.device {
		syscall.Close(fd)
		if err == nil {
			err = syscall.ENOENT
		}
		hidFail(id, linuxError(err, false))
	}
	handle := &hidDev{id}
	a.devices[handle] = &linuxDevice{fd: fd, path: node.device, numbered: numbered,
		readonly: readonly, zeroPrefixed: bus == 0x03 || bus == 0x18} // BUS_USB and BUS_I2C.
	a.openIDs[id] = true
	return handle
}

func (a *linuxHid) state(handle *hidDev, drain bool) *linuxDevice {
	state := a.devices[handle]
	if state == nil || (!drain && state.removed) {
		hidFail(handle.id, "disconnected")
	}
	return state
}

func (a *linuxHid) writable(handle *hidDev) *linuxDevice {
	state := a.state(handle, false)
	if state.readonly {
		hidFail(handle.id, "permission")
	}
	return state
}

func (d *linuxDevice) drain(handle *hidDev) {
	var buf [hidMaxLength + 1]byte
	for !d.removed {
		checkHidInterrupt()
		n, err := syscall.Read(d.fd, buf[:])
		switch {
		case err == syscall.EINTR:
			continue
		case err == syscall.EAGAIN:
			return
		case linuxMissing(err), err == syscall.EIO, err == nil && n == 0:
			d.removed = true
			return
		case err != nil:
			hidFail(handle.id, linuxError(err, true))
		}
		d.push(linuxInput(d.numbered, buf[:n]))
	}
}

func (a *linuxHid) read(handle *hidDev) Value {
	state := a.state(handle, true)
	state.drain(handle)
	if state.count != 0 {
		return state.pop()
	}
	a.state(handle, false)
	return nil
}

func (d *linuxDevice) checkIO(handle *hidDev, err error) {
	if err == nil {
		return
	}
	category := linuxError(err, true)
	if category == "disconnected" {
		d.removed = true
	}
	hidFail(handle.id, category)
}

func (a *linuxHid) send(handle *hidDev, feature bool, report hidReport) {
	state := a.writable(handle)
	data := linuxFrame(report.id, report.data)
	if feature {
		_, err := linuxFeatureIoctl(state.fd, linuxFeatureSet, data)
		state.checkIO(handle, err)
		return
	}
	n, err := syscall.Write(state.fd, data)
	state.checkIO(handle, err)
	if n != len(data) {
		hidFail(handle.id, "io")
	}
}

func (a *linuxHid) feature(handle *hidDev, id, length int64) Bytes {
	state := a.writable(handle)
	data := make([]byte, length+1)
	data[0] = byte(id)
	n, err := linuxFeatureIoctl(state.fd, linuxFeatureGet, data)
	state.checkIO(handle, err)
	if n < 0 || n > len(data) {
		hidFail(handle.id, "io")
	}
	return linuxFeaturePayload(id, data[:n], int(length), state.zeroPrefixed)
}

func (a *linuxHid) grab(handle *hidDev, on bool) {
	state := a.state(handle, !on)
	if !on {
		linuxEvdev.release(state.grabs)
		state.grabs = nil
		return
	}
	if len(state.grabs) != 0 {
		return
	}
	paths, err := linuxEventPaths(state.path, a.devRoot)
	if err != nil {
		hidFail(handle.id, linuxError(err, true))
	}
	if len(paths) == 0 {
		hidFail(handle.id, "unsupported")
	}
	state.grabs, err = linuxEvdev.acquire(paths)
	if err != nil {
		hidFail(handle.id, linuxError(err, true))
	}
}

type linuxWaitDevice struct {
	handle *hidDev
	state  *linuxDevice
}

func (d linuxWaitDevice) update(event int16) {
	if event&(linuxPollIn|linuxPollHup|linuxPollErr) != 0 {
		d.state.drain(d.handle)
	}
	if event&(linuxPollHup|linuxPollErr|linuxPollNval) != 0 {
		d.state.removed = true
	}
}

func linuxReady(devices []linuxWaitDevice) []Value {
	var ready []Value
	for i, d := range devices {
		if d.state.count != 0 || d.state.removed {
			ready = append(ready, int64(i))
		}
	}
	return ready
}

func (a *linuxHid) wait(handles []Value, timeout int64) []Value {
	devices := make([]linuxWaitDevice, len(handles))
	for i, value := range handles {
		handle := value.(*hidDev)
		devices[i] = linuxWaitDevice{handle, a.state(handle, true)}
	}
	wake, cleanup, err := linuxWakePipe(hidStopping)
	if err != nil {
		hidFail("", linuxError(err, true))
	}
	defer cleanup()
	deadline := time.Now().Add(time.Duration(timeout) * time.Millisecond)
	fds := make([]linuxPollFd, len(devices)+1)
	fds[0] = linuxPollFd{fd: int32(wake), events: linuxPollIn}
	for i, d := range devices {
		fd := int32(-1)
		if !d.state.removed {
			fd = int32(d.state.fd)
		}
		fds[i+1] = linuxPollFd{fd: fd, events: linuxPollIn}
	}
	for {
		remaining := time.Until(deadline)
		if len(linuxReady(devices)) > 0 {
			remaining = 0
		}
		err = linuxPoll(fds, remaining)
		checkHidInterrupt()
		if errors.Is(err, syscall.EINTR) {
			continue
		}
		if err != nil {
			hidFail("", linuxError(err, true))
		}
		for i, d := range devices {
			d.update(fds[i+1].revents)
		}
		ready := linuxReady(devices)
		if len(ready) != 0 || !time.Now().Before(deadline) {
			return ready
		}
	}
}

func (a *linuxHid) close(handle *hidDev) {
	state := a.devices[handle]
	if state == nil {
		return
	}
	delete(a.devices, handle)
	delete(a.openIDs, handle.id)
	linuxEvdev.release(state.grabs)
	syscall.Close(state.fd)
}

func (a *linuxHid) shutdown() {
	a.mu.Lock()
	defer a.mu.Unlock()
	for handle := range a.devices {
		a.close(handle)
	}
}

func (a *linuxHid) invoke(op string, args ...Value) Value {
	a.mu.Lock()
	defer a.mu.Unlock()
	checkHidInterrupt()
	switch op {
	case "enumerate":
		return a.enumerate()
	case "open":
		return a.open(args[0].(string))
	case "wait":
		return a.wait(args[0].([]Value), args[1].(int64))
	case "supports":
		switch args[0].(string) {
		case "enumerate", "read", "write", "feature", "grab":
			return true
		}
		return false
	}
	handle := args[0].(*hidDev)
	switch op {
	case "read":
		return a.read(handle)
	case "write", "feature-set":
		a.send(handle, op == "feature-set", args[1].(hidReport))
	case "feature-get":
		return a.feature(handle, args[1].(int64), args[2].(int64))
	case "grab":
		a.grab(handle, args[1].(bool))
	case "close":
		a.close(handle)
	}
	return U
}
