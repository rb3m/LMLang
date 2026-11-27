//go:build linux

package main

import (
	"errors"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"syscall"
	"time"
	"unsafe"
)

const (
	linuxOpenFlags  = syscall.O_NONBLOCK | syscall.O_CLOEXEC
	linuxFeatureSet = 0x06
	linuxFeatureGet = 0x07
	linuxEvGrab     = 1<<30 | 4<<16 | 'E'<<8 | 0x90
	linuxPollIn     = 0x001
	linuxPollErr    = 0x008
	linuxPollHup    = 0x010
	linuxPollNval   = 0x020
)

func linuxMissing(err error) bool {
	return errors.Is(err, syscall.ENOENT) || errors.Is(err, syscall.ENODEV) ||
		errors.Is(err, syscall.ENXIO)
}

func linuxError(err error, opened bool) string {
	switch {
	case errors.Is(err, syscall.EACCES), errors.Is(err, syscall.EPERM):
		return "permission"
	case errors.Is(err, syscall.EBUSY):
		return "busy"
	case linuxMissing(err) && opened:
		return "disconnected"
	case linuxMissing(err):
		return "not-found"
	}
	return "io"
}

type linuxUsage struct{ page, usage int64 }

type linuxDescriptor struct {
	page     int64
	pages    []int64
	local    *linuxUsage
	primary  linuxUsage
	found    bool
	numbered bool
}

func (d *linuxDescriptor) item(tag byte, size int, value int64) {
	d.numbered = d.numbered || (tag == 0x84 && size == 1)
	if d.found {
		return
	}
	switch tag {
	case 0x04: // Usage Page (global).
		d.page = value
	case 0xa4: // Push.
		d.pages = append(d.pages, d.page)
	case 0xb4: // Pop.
		if n := len(d.pages); n != 0 {
			d.page, d.pages = d.pages[n-1], d.pages[:n-1]
		}
	case 0x08: // Usage (local).
		if d.local == nil {
			d.local = linuxLocalUsage(d.page, size, value)
		}
	case 0xa0: // First Collection.
		d.found = true
		d.primary = linuxUsage{d.page, -1}
		if d.local != nil {
			d.primary = *d.local
		}
	}
	if tag&0x0c == 0 {
		d.local = nil // Local items apply only to the next main item.
	}
}

func linuxLocalUsage(page int64, size int, value int64) *linuxUsage {
	if size == 4 {
		return &linuxUsage{value >> 16, value & 0xffff}
	}
	return &linuxUsage{page, value}
}

func linuxDescriptorInfo(data []byte) (int64, int64, bool) {
	state := linuxDescriptor{page: -1, primary: linuxUsage{-1, -1}}
	for len(data) != 0 {
		prefix := data[0]
		data = data[1:]
		if prefix == 0xfe && (len(data) < 2 || len(data) < 2+int(data[0])) {
			break
		}
		if prefix == 0xfe {
			data = data[2+int(data[0]):]
			continue
		}
		size := [...]int{0, 1, 2, 4}[prefix&3]
		if len(data) < size {
			break
		}
		state.item(prefix&0xfc, size, linuxItemValue(data[:size]))
		data = data[size:]
	}
	return state.primary.page, state.primary.usage, state.numbered
}

func linuxItemValue(data []byte) int64 {
	var value int64
	for i, b := range data {
		value |= int64(b) << (8 * i)
	}
	return value
}

func linuxHex(s string) int64 {
	n, err := strconv.ParseUint(s, 16, 32)
	if err != nil {
		return -1
	}
	return int64(n)
}

func linuxUevent(device string) (bus, vendor, product int64, name, serial string) {
	data, _ := os.ReadFile(filepath.Join(device, "uevent"))
	return linuxParseUevent(strings.ToValidUTF8(string(data), "\uFFFD"))
}

func linuxParseUevent(text string) (bus, vendor, product int64, name, serial string) {
	props := make(map[string]string)
	for _, line := range strings.Split(text, "\n") {
		key, value, found := strings.Cut(line, "=")
		if found {
			props[key] = value
		}
	}
	bus, vendor, product = -1, -1, -1
	if parts := strings.Split(props["HID_ID"], ":"); len(parts) == 3 {
		bus, vendor, product = linuxHex(parts[0]), linuxHex(parts[1]), linuxHex(parts[2])
	}
	return bus, vendor, product, props["HID_NAME"], props["HID_UNIQ"]
}

func linuxInterface(device string) int64 {
	for dir := filepath.Dir(device); dir != filepath.Dir(dir); dir = filepath.Dir(dir) {
		if data, err := os.ReadFile(filepath.Join(dir, "bInterfaceNumber")); err == nil {
			return linuxHex(strings.TrimSpace(string(data)))
		}
	}
	return -1
}

func linuxChildren(path, prefix string) ([]string, error) {
	entries, err := os.ReadDir(path)
	if errors.Is(err, syscall.ENOENT) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	var names []string
	for _, entry := range entries {
		if strings.HasPrefix(entry.Name(), prefix) {
			names = append(names, entry.Name())
		}
	}
	return names, nil
}

func linuxEventPaths(device, devRoot string) ([]string, error) {
	root := filepath.Join(device, "input")
	groups, err := linuxChildren(root, "input")
	if err != nil {
		return nil, err
	}
	var paths []string
	for _, group := range groups {
		events, err := linuxChildren(filepath.Join(root, group), "event")
		if err != nil {
			return nil, err
		}
		paths = append(paths, linuxDevicePaths(filepath.Join(devRoot, "input"), events)...)
	}
	return paths, nil
}

func linuxDevicePaths(directory string, names []string) []string {
	paths := make([]string, len(names))
	for i, name := range names {
		paths[i] = filepath.Join(directory, name)
	}
	return paths
}

func linuxOpenRaw(path string) (fd int, readonly bool, err error) {
	fd, err = syscall.Open(path, syscall.O_RDWR|linuxOpenFlags, 0)
	if err != syscall.EACCES {
		return fd, false, err
	}
	fd, err = syscall.Open(path, syscall.O_RDONLY|linuxOpenFlags, 0)
	return fd, true, err
}

func linuxFrame(id int64, data Bytes) []byte {
	return append([]byte{byte(id)}, data...)
}

func linuxInput(numbered bool, data []byte) hidReport {
	if numbered {
		return hidReport{int64(data[0]), Bytes(data[1:])}
	}
	return hidReport{0, Bytes(data)}
}

func linuxFeaturePayload(id int64, data []byte, length int, zeroPrefixed bool) Bytes {
	// USB and I2C retain a synthetic ID byte for unnumbered replies.
	if (id != 0 || zeroPrefixed) && len(data) != 0 && data[0] == byte(id) {
		data = data[1:]
	}
	return Bytes(data[:min(len(data), length)])
}

func linuxFeatureRequest(command, size int) uintptr {
	// asm-generic _IOWR, shared by Linux amd64 and arm64.
	return 3<<30 | uintptr(size)<<16 | 'H'<<8 | uintptr(command)
}

func linuxFeatureIoctl(fd, command int, data []byte) (int, error) {
	size, _, err := syscall.Syscall(syscall.SYS_IOCTL, uintptr(fd),
		linuxFeatureRequest(command, len(data)), uintptr(unsafe.Pointer(&data[0])))
	if err != 0 {
		return 0, err
	}
	return int(size), nil
}

func linuxGrabIoctl(fd int, on bool) error {
	arg := uintptr(0)
	if on {
		arg = 1
	}
	_, _, err := syscall.Syscall(syscall.SYS_IOCTL, uintptr(fd), linuxEvGrab, arg)
	if err != 0 {
		return err
	}
	return nil
}

type linuxGrabOps struct {
	open  func(string) (int, error)
	ioctl func(int, bool) error
	close func(int) error
}

var linuxEvdev = linuxGrabOps{
	open:  func(path string) (int, error) { return syscall.Open(path, syscall.O_RDONLY|linuxOpenFlags, 0) },
	ioctl: linuxGrabIoctl,
	close: syscall.Close,
}

func (ops linuxGrabOps) acquire(paths []string) ([]int, error) {
	fds := make([]int, 0, len(paths))
	for _, path := range paths {
		fd, err := ops.acquireOne(path)
		if err != nil {
			ops.release(fds)
			return nil, err
		}
		fds = append(fds, fd)
	}
	return fds, nil
}

func (ops linuxGrabOps) acquireOne(path string) (int, error) {
	fd, err := ops.open(path)
	if err != nil {
		return -1, err
	}
	if err := ops.ioctl(fd, true); err != nil {
		ops.close(fd)
		return -1, err
	}
	return fd, nil
}

func (ops linuxGrabOps) release(fds []int) {
	for i := len(fds) - 1; i >= 0; i-- {
		ops.ioctl(fds[i], false)
		ops.close(fds[i])
	}
}

// Linux struct pollfd. ppoll is available on both supported architectures.
type linuxPollFd struct {
	fd      int32
	events  int16
	revents int16
}

func linuxPoll(fds []linuxPollFd, remaining time.Duration) error {
	timeout := syscall.NsecToTimespec(max(0, remaining.Nanoseconds()))
	_, _, err := syscall.Syscall6(syscall.SYS_PPOLL,
		uintptr(unsafe.Pointer(&fds[0])), uintptr(len(fds)),
		uintptr(unsafe.Pointer(&timeout)), 0, 0, 0)
	if err != 0 {
		return err
	}
	return nil
}

func linuxWakePipe(stopping <-chan struct{}) (int, func(), error) {
	var pipe [2]int
	if err := syscall.Pipe2(pipe[:], linuxOpenFlags); err != nil {
		return -1, nil, err
	}
	done, exited := make(chan struct{}), make(chan struct{})
	go func() {
		defer close(exited)
		select {
		case <-stopping:
			for {
				if _, err := syscall.Write(pipe[1], []byte{0}); err != syscall.EINTR {
					return
				}
			}
		case <-done:
		}
	}()
	cleanup := func() {
		close(done)
		<-exited
		syscall.Close(pipe[0])
		syscall.Close(pipe[1])
	}
	return pipe[0], cleanup, nil
}
