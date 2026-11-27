//go:build linux

package main

import (
	"os"
	"path/filepath"
	"reflect"
	"syscall"
	"testing"
	"time"
)

func TestLinuxHidDescriptor(t *testing.T) {
	cases := []struct {
		data        []byte
		page, usage int64
		numbered    bool
	}{
		{[]byte{5, 1, 9, 2, 0xa1, 1, 0x85, 1, 0xc0}, 1, 2, true},
		{[]byte{0xfe, 3, 0, 0x85, 0xaa, 0, 5, 0, 9, 0, 0xa1, 1, 0xc0}, 0, 0, false},
		{[]byte{0x85}, -1, -1, false},
		{[]byte{5, 1, 0xa1, 1, 9, 2, 0xc0}, 1, -1, false},
		{[]byte{0x0b, 3, 0, 12, 0, 0xa1, 1, 0xc0}, 12, 3, false},
	}
	for _, c := range cases {
		page, usage, numbered := linuxDescriptorInfo(c.data)
		if page != c.page || usage != c.usage || numbered != c.numbered {
			t.Errorf("%x: got (%d, %d, %t), want (%d, %d, %t)",
				c.data, page, usage, numbered, c.page, c.usage, c.numbered)
		}
	}
	bus, vendor, product, name, serial := linuxParseUevent("HID_ID=0003:0000046D:0000C52B\nHID_NAME=USB=Mouse\nbad\n")
	if bus != 3 || vendor != 0x046d || product != 0xc52b || name != "USB=Mouse" || serial != "" {
		t.Fatalf("unexpected uevent fields: %x %x %q %q", vendor, product, name, serial)
	}
}

func TestLinuxHidFraming(t *testing.T) {
	cases := []struct{ name, got, want string }{
		{"unnumbered frame", string(linuxFrame(0, "a")), "\x00a"},
		{"numbered frame", string(linuxFrame(3, "a")), "\x03a"},
		{"unnumbered feature", string(linuxFeaturePayload(0, []byte{0, 'a'}, 2, false)), "\x00a"},
		{"unnumbered USB feature", string(linuxFeaturePayload(0, []byte{0, 0, 'a'}, 2, true)), "\x00a"},
		{"numbered feature", string(linuxFeaturePayload(3, []byte{3, 'a'}, 2, false)), "a"},
		{"feature without ID byte", string(linuxFeaturePayload(3, []byte{4, 'a'}, 2, false)), "\x04a"},
	}
	for _, c := range cases {
		if c.got != c.want {
			t.Errorf("%s: got %q, want %q", c.name, c.got, c.want)
		}
	}
	if got := linuxInput(false, []byte{0, 'a'}); got != (hidReport{0, "\x00a"}) {
		t.Errorf("unnumbered input: %#v", got)
	}
	if got := linuxInput(true, []byte{3, 'a'}); got != (hidReport{3, "a"}) {
		t.Errorf("numbered input: %#v", got)
	}
	if linuxFeatureRequest(linuxFeatureSet, 91) != 0xc05b4806 ||
		linuxFeatureRequest(linuxFeatureGet, 91) != 0xc05b4807 || linuxEvGrab != 0x40044590 {
		t.Fatal("incorrect Linux ioctl encoding")
	}
}

func TestLinuxHidErrors(t *testing.T) {
	cases := []struct {
		err           error
		before, after string
	}{
		{syscall.EACCES, "permission", "permission"},
		{syscall.EPERM, "permission", "permission"},
		{syscall.EBUSY, "busy", "busy"},
		{syscall.ENOENT, "not-found", "disconnected"},
		{syscall.ENXIO, "not-found", "disconnected"},
		{syscall.ENODEV, "not-found", "disconnected"},
		{syscall.EIO, "io", "io"},
	}
	for _, c := range cases {
		if linuxError(c.err, false) != c.before || linuxError(c.err, true) != c.after {
			t.Errorf("incorrect mapping for %v", c.err)
		}
	}
}

func linuxTestAttachment(t *testing.T, sys, usb, node, id string) {
	t.Helper()
	device := filepath.Join(usb, id)
	if err := os.MkdirAll(device, 0700); err != nil {
		t.Fatal(err)
	}
	attrs := map[string]string{
		filepath.Join(usb, "bInterfaceNumber"):     "0a\n",
		filepath.Join(device, "uevent"):            "HID_ID=0003:046D:C52B\nHID_NAME=A mouse\n",
		filepath.Join(device, "report_descriptor"): "\x05\x01\x09\x02\xa1\x01\x85\x01\xc0",
	}
	for path, content := range attrs {
		if err := os.WriteFile(path, []byte(content), 0600); err != nil {
			t.Fatal(err)
		}
	}
	class := filepath.Join(sys, node)
	if err := os.MkdirAll(class, 0700); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(device, filepath.Join(class, "device")); err != nil {
		t.Fatal(err)
	}
}

func TestLinuxHidEnumerationAndWait(t *testing.T) {
	root := t.TempDir()
	sys, usb := filepath.Join(root, "class"), filepath.Join(root, "usb-interface")
	linuxTestAttachment(t, sys, usb, "hidraw0", "0003:046D:C52B.0007")
	linuxTestAttachment(t, sys, usb, "hidraw1", "0003:046D:C52B.0002")
	if err := os.WriteFile(filepath.Join(root, "hidraw0"), []byte("\x01abc"), 0600); err != nil {
		t.Fatal(err)
	}
	a := makeLinuxHid(sys, root)
	t.Cleanup(a.shutdown)
	want := [][]Value{
		{"linux:0003:046d:c52b.0002", int64(0x046d), int64(0xc52b), int64(1), int64(2), int64(10), "A mouse", ""},
		{"linux:0003:046d:c52b.0007", int64(0x046d), int64(0xc52b), int64(1), int64(2), int64(10), "A mouse", ""},
	}
	if got := a.enumerate(); !reflect.DeepEqual(got, want) {
		t.Fatalf("enumerate: got %#v, want %#v", got, want)
	}
	handle := a.open(want[1][0].(string))
	if got := a.wait([]Value{handle, handle}, 0); !reflect.DeepEqual(got, []Value{int64(0), int64(1)}) {
		t.Fatalf("wait: got %#v", got)
	}
	if got := a.read(handle); got != (hidReport{1, "abc"}) {
		t.Fatalf("read: got %#v", got)
	}
	if state := a.devices[handle]; !state.removed || state.count != 0 {
		t.Fatal("EOF should keep the queue readable until it drains")
	}
}

func TestLinuxHidQueue(t *testing.T) {
	device := &linuxDevice{}
	for i := int64(0); i < hidMaxQueue+2; i++ {
		device.push(hidReport{i, "a"})
	}
	if device.count != hidMaxQueue {
		t.Fatalf("queue contains %d reports", device.count)
	}
	for i := int64(2); i < hidMaxQueue+2; i++ {
		if report := device.pop(); report.id != i {
			t.Fatalf("got report %d, want %d", report.id, i)
		}
	}
}

func TestLinuxHidGrabRollback(t *testing.T) {
	var opened []string
	var closed, grabs, releases []int
	ops := linuxGrabOps{
		open: func(path string) (int, error) {
			opened = append(opened, path)
			return len(opened), nil
		},
		ioctl: func(fd int, on bool) error {
			if !on {
				releases = append(releases, fd)
				return nil
			}
			grabs = append(grabs, fd)
			if fd == 2 {
				return syscall.EBUSY
			}
			return nil
		},
		close: func(fd int) error {
			closed = append(closed, fd)
			return nil
		},
	}
	fds, err := ops.acquire([]string{"event0", "event1", "event2"})
	if fds != nil || err != syscall.EBUSY ||
		!reflect.DeepEqual(opened, []string{"event0", "event1"}) ||
		!reflect.DeepEqual(grabs, []int{1, 2}) || !reflect.DeepEqual(releases, []int{1}) ||
		!reflect.DeepEqual(closed, []int{2, 1}) {
		t.Fatalf("rollback: fds=%v err=%v opened=%v grabs=%v releases=%v closed=%v",
			fds, err, opened, grabs, releases, closed)
	}
}

func TestLinuxHidWakePipe(t *testing.T) {
	stopping := make(chan struct{})
	fd, cleanup, err := linuxWakePipe(stopping)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(cleanup)
	close(stopping)
	fds := []linuxPollFd{{fd: int32(fd), events: linuxPollIn}}
	deadline := time.Now().Add(time.Second)
	for {
		err = linuxPoll(fds, time.Until(deadline))
		if err == syscall.EINTR {
			continue
		}
		if err != nil || fds[0].revents&linuxPollIn == 0 {
			t.Fatalf("wake pipe: events=%x error=%v", fds[0].revents, err)
		}
		return
	}
}
