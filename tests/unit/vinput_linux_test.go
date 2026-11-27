//go:build linux

package main

import (
	"bytes"
	"encoding/hex"
	"reflect"
	"runtime"
	"syscall"
	"testing"
)

func TestVinputABI(t *testing.T) {
	actual := []uintptr{uiDevCreate, uiDevDestroy, uiDevSetup, uiAbsSetup, uiSetEvBit, uiSetKeyBit, uiSetAbsBit}
	want := []uintptr{0x5501, 0x5502, 0x405c5503, 0x401c5504, 0x40045564, 0x40045565, 0x40045567}
	if !reflect.DeepEqual(actual, want) {
		t.Fatalf("ioctls = %x, want %x", actual, want)
	}
	for i, axis := range []string{"x", "y", "z", "rx", "ry", "rz", "throttle", "rudder", "wheel", "gas", "brake"} {
		if code, ok := vinputAxisCodes[axis]; !ok || code != uint16(i) {
			t.Fatalf("axis %s has code %d", axis, code)
		}
	}
	for i, code := range map[int]uint16{0: 0x120, 15: 0x12f, 16: 0x2c0, 55: 0x2e7} {
		if actual := vinputButtonCode(i); actual != code {
			t.Fatalf("button %d = %x, want %x", i, actual, code)
		}
	}
	for err, want := range map[error]string{syscall.EPERM: "permission", syscall.EACCES: "permission",
		syscall.ENOENT: "unsupported", syscall.ENODEV: "unsupported", syscall.EBUSY: "busy", syscall.ENOTTY: "io"} {
		if actual := uinputCategory(err); actual != want {
			t.Fatalf("%v maps to %q, want %q", err, actual, want)
		}
	}
}

func checkVinputBytes(t *testing.T, got []byte, prefix string, zeros int) {
	t.Helper()
	want, err := hex.DecodeString(prefix)
	if err != nil {
		t.Fatal(err)
	}
	want = append(want, make([]byte, zeros)...)
	if !bytes.Equal(got, want) {
		t.Fatalf("packed %x, want %x", got, want)
	}
}

func TestVinputStructs(t *testing.T) {
	if runtime.GOARCH != "amd64" && runtime.GOARCH != "arm64" {
		t.Skip("64-bit Linux ABI")
	}
	checkVinputBytes(t, packVinputDevice(vinputSpec{Name: "Joy", Vendor: 0x1234, Product: 0xfedc}),
		"06003412dcfe01004a6f79", 81)
	checkVinputBytes(t, packVinputAbs(5, -1, -2, 1), "05000000fffffffffeffffff01000000", 12)
	checkVinputBytes(t, appendVinputEvent(nil, 3, 5, -2),
		"0000000000000000000000000000000003000500feffffff", 0)
}

func TestVinputEmptyDevice(t *testing.T) {
	if types := vinputEventTypes(vinputSpec{}); !reflect.DeepEqual(types, []uint16{vinputSyn}) {
		t.Fatalf("empty joystick enabled ioctl types %v", types)
	}
}

func TestVinputAdapter(t *testing.T) {
	var calls []uintptr
	var writes [][]byte
	var closed int
	var failWrite bool
	kernel := linuxVinput{
		open: func(path string, flags int, mode uint32) (int, error) {
			if path != "/dev/uinput" || flags != syscall.O_WRONLY|syscall.O_NONBLOCK|syscall.O_CLOEXEC || mode != 0 {
				t.Fatalf("open(%s, %x, %d)", path, flags, mode)
			}
			return 97, nil
		},
		ioctl: func(fd int, op uintptr, value uint16, buf []byte) error {
			if fd != 97 {
				t.Fatalf("wrong fd %d", fd)
			}
			calls = append(calls, op)
			if op == uiAbsSetup && len(calls) == 7 {
				checkVinputBytes(t, buf, "05000000fffffffffeffffff01000000", 12)
			}
			return nil
		},
		write: func(fd int, buf []byte) (int, error) {
			writes = append(writes, buf)
			if failWrite {
				return 0, nil
			}
			return len(buf), nil
		},
		close: func(int) error { closed++; return nil },
	}
	spec := vinputSpec{Name: "Joy", Axes: []vinputAxis{{"rz", -2, 1}}, Buttons: 1, Hats: 1}
	output, category := kernel.create("v1", spec)
	if category != "" || len(writes) != 0 {
		t.Fatalf("unexpected create result %q, writes %v", category, writes)
	}
	wantCalls := []uintptr{uiSetEvBit, uiSetEvBit, uiSetEvBit, uiSetKeyBit, uiDevSetup, uiSetAbsBit,
		uiAbsSetup, uiSetAbsBit, uiAbsSetup, uiSetAbsBit, uiAbsSetup, uiDevCreate}
	if !reflect.DeepEqual(calls, wantCalls) {
		t.Fatalf("ioctl calls %x, want %x", calls, wantCalls)
	}

	dev := makeVinputDev("v1", spec, output)
	adapter := &vinputAdapter{opened: []*vinputDev{dev}}
	adapter.invoke("axis", dev, "rz", int64(-1))
	adapter.invoke("sync", dev)
	adapter.invoke("hat", dev, int64(0), int64(0), int64(-1))
	adapter.invoke("button", dev, int64(0), true)
	adapter.invoke("axis", dev, "rz", int64(1))
	failWrite = true
	kind, _, fail, _ := outcome(func() Value { return adapter.invoke("sync", dev) })
	if kind != "fail" || fail.String() != `(fail vinput.VinputError "v1" "io")` {
		t.Fatalf("short write: %s, %v", kind, fail)
	}
	failWrite = false
	adapter.invoke("sync", dev)
	adapter.invoke("sync", dev)
	end := appendVinputEvent(nil, 0, 0, 0)
	frame := appendVinputEvent(nil, 3, 5, 1)
	frame = appendVinputEvent(frame, 1, 0x120, 1)
	frame = appendVinputEvent(frame, 3, 17, -1)
	frame = append(frame, end...)
	if !reflect.DeepEqual(writes, [][]byte{end, frame, frame, end}) {
		t.Fatalf("wrong frames %x", writes)
	}
	adapter.invoke("close", dev)
	adapter.invoke("close", dev)
	adapter.shutdown()
	if closed != 1 || len(calls) != len(wantCalls)+1 || calls[len(calls)-1] != uiDevDestroy {
		t.Fatalf("close count %d, ioctl calls %x", closed, calls)
	}
}
