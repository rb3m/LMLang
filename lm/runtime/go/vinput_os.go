//go:build !linux

package main

func osVinput() vinputBackend { return nil }
