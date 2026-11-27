package main

func startDevices() {
	startHid()
	startVinput()
}

func closeDevices() {
	closeHid()
	closeVinput()
}

func stopDevices() {
	stopHid()
	closeVinput()
	activeVinput = nil
}
