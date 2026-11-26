//go:build darwin && cgo

package main

import "strconv"

func darwinDeviceID(id uint64) string { return "darwin:" + strconv.FormatUint(id, 16) }

func darwinFrame(id int64, data Bytes) Bytes {
	if id == 0 {
		return data
	}
	return Bytes([]byte{byte(id)}) + data
}

func darwinInput(id int64, data Bytes) Bytes {
	if id != 0 && len(data) != 0 {
		return data[1:]
	}
	return data
}

func darwinFeature(id int64, data Bytes) Bytes {
	if id != 0 && len(data) != 0 && data[0] == byte(id) {
		return data[1:]
	}
	return data
}

func (a *darwinHid) shutdown() {
	a.mu.Lock()
	defer a.mu.Unlock()
	for handle := range a.devices {
		a.close(handle)
	}
}

func (a *darwinHid) invoke(op string, args ...Value) Value {
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
	case "write":
		a.send(handle, false, args[1].(hidReport))
	case "feature-set":
		a.send(handle, true, args[1].(hidReport))
	case "feature-get":
		return a.feature(handle, args[1].(int64), args[2].(int64))
	case "grab":
		a.grab(handle, args[1].(bool))
	case "close":
		a.close(handle)
	}
	return U
}
