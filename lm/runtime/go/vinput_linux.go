//go:build linux

package main

import (
	"encoding/binary"
	"errors"
	"math"
	"syscall"
	"unsafe"
)

const (
	vinputSyn     = 0
	vinputKey     = 1
	vinputAbs     = 3
	vinputHat0X   = 0x10
	uinputType    = uintptr('U') << 8
	uinputWrite   = 1 << 30
	uiDevCreate   = uinputType | 1
	uiDevDestroy  = uinputType | 2
	uiDevSetup    = uinputWrite | 92<<16 | uinputType | 3
	uiAbsSetup    = uinputWrite | 28<<16 | uinputType | 4
	uiSetEvBit    = uinputWrite | 4<<16 | uinputType | 100
	uiSetKeyBit   = uinputWrite | 4<<16 | uinputType | 101
	uiSetAbsBit   = uinputWrite | 4<<16 | uinputType | 103
	inputEventLen = int(unsafe.Sizeof(syscall.Timeval{})) + 8
)

func vinputButtonCode(i int) uint16 {
	if i < 16 {
		return uint16(0x120 + i)
	}
	return uint16(0x2c0 + i - 16)
}

func packVinputDevice(spec vinputSpec) []byte {
	buf := make([]byte, 92)
	binary.NativeEndian.PutUint16(buf, 6)
	binary.NativeEndian.PutUint16(buf[2:], uint16(spec.Vendor))
	binary.NativeEndian.PutUint16(buf[4:], uint16(spec.Product))
	binary.NativeEndian.PutUint16(buf[6:], 1)
	copy(buf[8:88], spec.Name)
	return buf
}

func packVinputAbs(code uint16, value, low, high int64) []byte {
	buf := make([]byte, 28)
	binary.NativeEndian.PutUint16(buf, code)
	binary.NativeEndian.PutUint32(buf[4:], uint32(value))
	binary.NativeEndian.PutUint32(buf[8:], uint32(low))
	binary.NativeEndian.PutUint32(buf[12:], uint32(high))
	return buf
}

func appendVinputEvent(buf []byte, kind, code uint16, value int64) []byte {
	buf = append(buf, make([]byte, inputEventLen)...)
	tail := buf[len(buf)-8:]
	binary.NativeEndian.PutUint16(tail, kind)
	binary.NativeEndian.PutUint16(tail[2:], code)
	binary.NativeEndian.PutUint32(tail[4:], uint32(value))
	return buf
}

func uinputCategory(err error) string {
	switch {
	case err == nil:
		return ""
	case errors.Is(err, syscall.EACCES), errors.Is(err, syscall.EPERM):
		return "permission"
	case errors.Is(err, syscall.ENOENT), errors.Is(err, syscall.ENODEV):
		return "unsupported"
	case errors.Is(err, syscall.EBUSY):
		return "busy"
	default:
		return "io"
	}
}

type linuxVinput struct {
	open  func(string, int, uint32) (int, error)
	ioctl func(int, uintptr, uint16, []byte) error
	write func(int, []byte) (int, error)
	close func(int) error
}

func osVinput() vinputBackend {
	return linuxVinput{syscall.Open, uinputIoctl, syscall.Write, syscall.Close}
}

func uinputIoctl(fd int, request uintptr, value uint16, data []byte) error {
	var errno syscall.Errno
	if len(data) == 0 {
		_, _, errno = syscall.Syscall(syscall.SYS_IOCTL, uintptr(fd), request, uintptr(value))
	}
	if len(data) != 0 {
		_, _, errno = syscall.Syscall(syscall.SYS_IOCTL, uintptr(fd), request, uintptr(unsafe.Pointer(&data[0])))
	}
	if errno != 0 {
		return errno
	}
	return nil
}

func (a linuxVinput) create(_ string, spec vinputSpec) (vinputOutput, string) {
	for _, axis := range spec.Axes {
		if axis.Min < math.MinInt32 || axis.Max > math.MaxInt32 {
			return nil, "io"
		}
	}
	fd, err := a.open("/dev/uinput", syscall.O_WRONLY|syscall.O_NONBLOCK|syscall.O_CLOEXEC, 0)
	if err != nil {
		return nil, uinputCategory(err)
	}
	if err := a.configure(fd, spec); err != nil {
		_ = a.close(fd)
		return nil, uinputCategory(err)
	}
	return linuxJoystick{a, fd}, ""
}

func vinputEventTypes(spec vinputSpec) []uint16 {
	var kinds []uint16
	if spec.Buttons > 0 {
		kinds = append(kinds, vinputKey)
	}
	if len(spec.Axes) > 0 || spec.Hats > 0 {
		kinds = append(kinds, vinputAbs)
	}
	return append(kinds, vinputSyn)
}

func (a linuxVinput) configure(fd int, spec vinputSpec) error {
	kinds := vinputEventTypes(spec)
	for _, kind := range kinds {
		if err := a.ioctl(fd, uiSetEvBit, kind, nil); err != nil {
			return err
		}
	}
	for i := 0; i < int(spec.Buttons); i++ {
		if err := a.ioctl(fd, uiSetKeyBit, vinputButtonCode(i), nil); err != nil {
			return err
		}
	}
	if err := a.ioctl(fd, uiDevSetup, 0, packVinputDevice(spec)); err != nil {
		return err
	}
	for _, axis := range spec.Axes {
		if err := a.setupAbs(fd, vinputAxisCodes[axis.Name], axis.midpoint(), axis.Min, axis.Max); err != nil {
			return err
		}
	}
	for i := 0; i < int(2*spec.Hats); i++ {
		if err := a.setupAbs(fd, vinputHat0X+uint16(i), 0, -1, 1); err != nil {
			return err
		}
	}
	return a.ioctl(fd, uiDevCreate, 0, nil)
}

func (a linuxVinput) setupAbs(fd int, code uint16, value, low, high int64) error {
	if err := a.ioctl(fd, uiSetAbsBit, code, nil); err != nil {
		return err
	}
	return a.ioctl(fd, uiAbsSetup, 0, packVinputAbs(code, value, low, high))
}

type linuxJoystick struct {
	adapter linuxVinput
	fd      int
}

func packVinputFrame(dev *vinputDev, events [][]any) []byte {
	var buf []byte
	for _, event := range events {
		switch event[0] {
		case "axis":
			buf = appendVinputEvent(buf, vinputAbs, vinputAxisCodes[event[1].(string)], event[2].(int64))
		case "button":
			var value int64
			if event[2].(bool) {
				value = 1
			}
			buf = appendVinputEvent(buf, vinputKey, vinputButtonCode(event[1].(int)), value)
		case "hat":
			buf = appendVinputHat(buf, dev.hats[event[1].(int)], event[1].(int))
		}
	}
	return appendVinputEvent(buf, vinputSyn, 0, 0)
}

func appendVinputHat(buf []byte, hat vinputControl[[2]int64], index int) []byte {
	for i, value := range hat.pending {
		if value != hat.sent[i] {
			buf = appendVinputEvent(buf, vinputAbs, vinputHat0X+uint16(2*index+i), value)
		}
	}
	return buf
}

func (d linuxJoystick) frame(dev *vinputDev, events [][]any) string {
	buf := packVinputFrame(dev, events)
	n, err := d.adapter.write(d.fd, buf)
	if err == nil && n != len(buf) {
		return "io"
	}
	return uinputCategory(err)
}

func (d linuxJoystick) close() string {
	destroyErr := d.adapter.ioctl(d.fd, uiDevDestroy, 0, nil)
	closeErr := d.adapter.close(d.fd)
	if destroyErr != nil {
		return uinputCategory(destroyErr)
	}
	return uinputCategory(closeErr)
}
