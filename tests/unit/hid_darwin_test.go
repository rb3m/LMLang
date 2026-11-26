package main

import "testing"

func TestDarwinHidHelpers(t *testing.T) {
	cases := []struct {
		name string
		got  string
		want string
	}{
		{"device id", darwinDeviceID(0xfedcba9876543210), "darwin:fedcba9876543210"},
		{"unnumbered output", string(darwinFrame(0, "\x00a")), "\x00a"},
		{"numbered output", string(darwinFrame(3, "\x03a")), "\x03\x03a"},
		{"unnumbered input", string(darwinInput(0, "\x00a")), "\x00a"},
		{"numbered input", string(darwinInput(3, "\x03\x03a")), "\x03a"},
		{"empty numbered payload", string(darwinInput(3, "\x03")), ""},
		{"numbered feature", string(darwinFeature(3, "\x03a")), "a"},
		{"feature without ID byte", string(darwinFeature(3, "\x04a")), "\x04a"},
		{"unnumbered feature", string(darwinFeature(0, "\x00a")), "\x00a"},
		{"permission", darwinError(0xe00002e2, false), "permission"},
		{"busy", darwinError(0xe00002c5, false), "busy"},
		{"open returned not attached", darwinError(0xe00002d9, false), "io"},
		{"disconnected", darwinError(0xe00002d9, true), "disconnected"},
		{"other I/O error", darwinError(0xe00002bc, false), "io"},
	}
	for _, c := range cases {
		if c.got != c.want {
			t.Errorf("%s: got %q, want %q", c.name, c.got, c.want)
		}
	}
}
