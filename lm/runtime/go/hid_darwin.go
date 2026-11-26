//go:build darwin && cgo

package main

/*
#cgo LDFLAGS: -framework IOKit -framework CoreFoundation
#include <CoreFoundation/CoreFoundation.h>
#include <IOKit/IOKitLib.h>
#include <IOKit/hid/IOHIDManager.h>
#include <IOKit/hidsystem/IOHIDLib.h>
#include <stdbool.h>
#include <stdlib.h>
#include <string.h>

typedef struct {
	uint32_t id;
	CFIndex length;
	uint8_t *data;
} HidReport;

typedef struct {
	IOHIDDeviceRef ref;
	CFRunLoopRef loop;
	uint8_t *buffer;
	CFIndex capacity;
	IOOptionBits options;
	bool opened, removed;
	size_t head, count, queue_size;
	HidReport ring[];
} HidDevice;

typedef struct {
	IOHIDManagerRef manager;
	CFSetRef matches;
	CFIndex count;
	IOHIDDeviceRef *refs;
} HidScan;

static bool scan_devices(HidScan *scan) {
	scan->manager = IOHIDManagerCreate(NULL, kIOHIDOptionsTypeNone);
	if (!scan->manager) return false;
	IOHIDManagerSetDeviceMatching(scan->manager, NULL);
	scan->matches = IOHIDManagerCopyDevices(scan->manager);
	if (!scan->matches) return true;

	scan->count = CFSetGetCount(scan->matches);
	scan->refs = calloc((size_t)scan->count, sizeof(*scan->refs));
	if (scan->count && scan->refs) CFSetGetValues(scan->matches, (const void **)scan->refs);
	return !scan->count || scan->refs;
}

static void end_scan(HidScan *scan) {
	free(scan->refs);
	if (scan->matches) CFRelease(scan->matches);
	if (scan->manager) CFRelease(scan->manager);
}

static bool registry_id(IOHIDDeviceRef ref, uint64_t *id) {
	io_service_t service = IOHIDDeviceGetService(ref);
	return service && IORegistryEntryGetRegistryEntryID(service, id) == kIOReturnSuccess;
}

static int64_t number_property(IOHIDDeviceRef ref, CFStringRef key) {
	CFTypeRef value = IOHIDDeviceGetProperty(ref, key);
	int64_t number;
	if (value && CFGetTypeID(value) == CFNumberGetTypeID()
	    && CFNumberGetValue(value, kCFNumberSInt64Type, &number)) return number;
	return -1;
}

static char *string_property(IOHIDDeviceRef ref, CFStringRef key) {
	CFTypeRef value = IOHIDDeviceGetProperty(ref, key);
	if (!value || CFGetTypeID(value) != CFStringGetTypeID()) return NULL;
	CFStringRef text = (CFStringRef)value;
	CFIndex size = CFStringGetMaximumSizeForEncoding(CFStringGetLength(text), kCFStringEncodingUTF8);
	if (size < 0) return NULL;
	char *buffer = malloc((size_t)size + 1);
	if (buffer && !CFStringGetCString(text, buffer, size + 1, kCFStringEncodingUTF8)) {
		free(buffer);
		return NULL;
	}
	return buffer;
}

static bool pop_report(HidDevice *device, HidReport *report) {
	if (!device->count) return false;
	*report = device->ring[device->head];
	device->head = (device->head + 1) % device->queue_size;
	device->count--;
	return true;
}

static void received(void *context, IOReturn status, void *sender, IOHIDReportType type,
                     uint32_t id, uint8_t *report, CFIndex length) {
	HidDevice *device = context;
	if (device->removed || status != kIOReturnSuccess || length < 0 || length > device->capacity) return;
	uint8_t *copy = length ? malloc((size_t)length) : NULL;
	if (length && !copy) return;
	if (length) memcpy(copy, report, (size_t)length);

	HidReport oldest;
	if (device->count == device->queue_size && pop_report(device, &oldest)) free(oldest.data);
	size_t tail = (device->head + device->count) % device->queue_size;
	device->ring[tail] = (HidReport){id, length, copy};
	device->count++;
}

static void removed(void *context, IOReturn status, void *sender) {
	((HidDevice *)context)->removed = true;
}

static HidDevice *make_device(IOHIDDeviceRef match, CFIndex minimum_capacity, size_t queue_size) {
	// Give the handle its own IOHIDDevice, separate from the manager's match.
	IOHIDDeviceRef ref = IOHIDDeviceCreate(NULL, IOHIDDeviceGetService(match));
	if (!ref) return NULL;
	HidDevice *device = calloc(1, sizeof(*device) + queue_size * sizeof(HidReport));
	CFIndex declared = number_property(ref, CFSTR(kIOHIDMaxInputReportSizeKey));
	CFIndex capacity = declared > minimum_capacity ? declared : minimum_capacity;
	uint8_t *buffer = malloc((size_t)capacity);
	if (!device || !buffer) {
		free(buffer);
		free(device);
		CFRelease(ref);
		return NULL;
	}
	device->ref = ref;
	device->loop = CFRunLoopGetCurrent();
	device->buffer = buffer;
	device->capacity = capacity;
	device->queue_size = queue_size;
	return device;
}

static void request_access(IOReturn status) {
	static bool prompted;
	if (status != kIOReturnNotPermitted || prompted) return;
	prompted = true;
	if (__builtin_available(macOS 10.15, *)) IOHIDRequestAccess(kIOHIDRequestTypeListenEvent);
}

static IOReturn start_device(HidDevice *device, IOOptionBits options) {
	IOReturn result = IOHIDDeviceOpen(device->ref, options);
	if (result != kIOReturnSuccess) {
		request_access(result);
		return result;
	}
	device->opened = true;
	device->options = options;
	IOHIDDeviceRegisterInputReportCallback(device->ref, device->buffer, device->capacity,
	                                      received, device);
	IOHIDDeviceRegisterRemovalCallback(device->ref, removed, device);
	IOHIDDeviceScheduleWithRunLoop(device->ref, device->loop, kCFRunLoopDefaultMode);
	return result;
}

static void stop_device(HidDevice *device) {
	if (!device->opened) return;
	IOHIDDeviceUnscheduleFromRunLoop(device->ref, device->loop, kCFRunLoopDefaultMode);
	IOHIDDeviceRegisterInputReportCallback(device->ref, device->buffer, device->capacity, NULL, device);
	IOHIDDeviceRegisterRemovalCallback(device->ref, NULL, device);
	IOHIDDeviceClose(device->ref, device->options);
	device->opened = false;
}

static void free_device(HidDevice *device) {
	stop_device(device);
	CFRelease(device->ref);
	HidReport report;
	while (pop_report(device, &report)) free(report.data);
	free(device->buffer);
	free(device);
}

static CFRunLoopRunResult pump(double seconds, bool stop_after_source) {
	return CFRunLoopRunInMode(kCFRunLoopDefaultMode, seconds, stop_after_source);
}

static void device_info(IOHIDDeviceRef ref, int64_t *numbers, char **strings) {
	numbers[0] = number_property(ref, CFSTR(kIOHIDVendorIDKey));
	numbers[1] = number_property(ref, CFSTR(kIOHIDProductIDKey));
	numbers[2] = number_property(ref, CFSTR(kIOHIDPrimaryUsagePageKey));
	numbers[3] = number_property(ref, CFSTR(kIOHIDPrimaryUsageKey));
	strings[0] = string_property(ref, CFSTR(kIOHIDProductKey));
	strings[1] = string_property(ref, CFSTR(kIOHIDSerialNumberKey));
}
*/
import "C"

import (
	"runtime"
	"sort"
	"sync"
	"time"
	"unsafe"
)

func init() { runtime.LockOSThread() }

type darwinHid struct {
	mu      sync.Mutex
	devices map[*hidDev]*C.HidDevice
	openIDs map[string]bool
}

func osHid() hidAdapter {
	return &darwinHid{devices: make(map[*hidDev]*C.HidDevice), openIDs: make(map[string]bool)}
}

func darwinError(status uint32, opened bool) string {
	switch int32(status) {
	case C.kIOReturnNotPermitted:
		return "permission"
	case C.kIOReturnExclusiveAccess:
		return "busy"
	case C.kIOReturnNoDevice, C.kIOReturnOffline, C.kIOReturnNotAttached:
		if opened {
			return "disconnected"
		}
	}
	return "io"
}

func darwinScan(id string, visit func(string, C.IOHIDDeviceRef) bool) {
	var scan C.HidScan
	ok := C.scan_devices(&scan)
	defer C.end_scan(&scan)
	if !ok {
		hidFail(id, "io")
	}
	for _, ref := range unsafe.Slice(scan.refs, int(scan.count)) {
		var registry C.uint64_t
		if bool(C.registry_id(ref, &registry)) && visit(darwinDeviceID(uint64(registry)), ref) {
			return
		}
	}
}

func (a *darwinHid) enumerate() [][]Value {
	var rows [][]Value
	darwinScan("", func(id string, ref C.IOHIDDeviceRef) bool {
		var numbers [4]C.int64_t
		var strings [2]*C.char
		C.device_info(ref, &numbers[0], &strings[0])
		rows = append(rows, []Value{id, int64(numbers[0]), int64(numbers[1]),
			int64(numbers[2]), int64(numbers[3]), int64(-1), C.GoString(strings[0]), C.GoString(strings[1])})
		C.free(unsafe.Pointer(strings[0]))
		C.free(unsafe.Pointer(strings[1]))
		return false
	})
	sort.Slice(rows, func(i, j int) bool { return rows[i][0].(string) < rows[j][0].(string) })
	return rows
}

func (a *darwinHid) open(id string) *hidDev {
	if a.openIDs[id] {
		hidFail(id, "busy")
	}
	var state *C.HidDevice
	darwinScan(id, func(candidate string, ref C.IOHIDDeviceRef) bool {
		if candidate != id {
			return false
		}
		state = C.make_device(ref, hidMaxLength+1, hidMaxQueue)
		if state == nil {
			hidFail(id, "io")
		}
		return true
	})
	if state == nil {
		hidFail(id, "not-found")
	}
	if status := C.start_device(state, 0); status != 0 {
		C.free_device(state)
		hidFail(id, darwinError(uint32(status), false))
	}
	handle := &hidDev{id}
	a.devices[handle], a.openIDs[id] = state, true
	return handle
}

func (a *darwinHid) state(handle *hidDev, drain bool) *C.HidDevice {
	state := a.devices[handle]
	if state == nil || (!drain && bool(state.removed)) {
		hidFail(handle.id, "disconnected")
	}
	return state
}

func (a *darwinHid) read(handle *hidDev) Value {
	C.pump(0, false)
	state := a.state(handle, true)
	var report C.HidReport
	if C.pop_report(state, &report) {
		data := Bytes(C.GoStringN((*C.char)(unsafe.Pointer(report.data)), C.int(report.length)))
		C.free(unsafe.Pointer(report.data))
		id := int64(report.id)
		return hidReport{id, darwinInput(id, data)}
	}
	a.state(handle, false)
	return nil
}

func darwinCheckIO(handle *hidDev, state *C.HidDevice, status C.IOReturn) {
	if status == 0 {
		return
	}
	category := darwinError(uint32(status), true)
	if category == "disconnected" {
		state.removed = true
	}
	hidFail(handle.id, category)
}

func (a *darwinHid) send(handle *hidDev, feature bool, report hidReport) {
	kind := C.IOHIDReportType(C.kIOHIDReportTypeOutput)
	if feature {
		kind = C.kIOHIDReportTypeFeature
	}
	state := a.state(handle, false)
	data := []byte(darwinFrame(report.id, report.data))
	status := C.IOHIDDeviceSetReport(state.ref, kind, C.CFIndex(report.id), (*C.uint8_t)(&data[0]), C.CFIndex(len(data)))
	darwinCheckIO(handle, state, status)
}

func (a *darwinHid) feature(handle *hidDev, id, length int64) Bytes {
	state := a.state(handle, false)
	size := C.CFIndex(length)
	if id != 0 {
		size++
	}
	data := make([]byte, size)
	status := C.IOHIDDeviceGetReport(state.ref, C.kIOHIDReportTypeFeature, C.CFIndex(id), (*C.uint8_t)(&data[0]), &size)
	darwinCheckIO(handle, state, status)
	if size < 0 || int(size) > len(data) {
		hidFail(handle.id, "io")
	}
	payload := darwinFeature(id, Bytes(data[:size]))
	if int64(len(payload)) > length {
		return payload[:length]
	}
	return payload
}

func (a *darwinHid) grab(handle *hidDev, on bool) {
	state := a.state(handle, false)
	previous, options := state.options, C.IOOptionBits(C.kIOHIDOptionsTypeNone)
	if on {
		options = C.kIOHIDOptionsTypeSeizeDevice
	}
	if previous == options {
		return
	}
	C.stop_device(state)
	status := C.start_device(state, options)
	if status == 0 {
		return
	}
	if C.start_device(state, previous) != 0 {
		state.removed = true
	}
	hidFail(handle.id, darwinError(uint32(status), false))
}

func (a *darwinHid) wait(handles []Value, timeout int64) []Value {
	states := make([]*C.HidDevice, len(handles))
	for i, handle := range handles {
		states[i] = a.state(handle.(*hidDev), true)
	}
	deadline := time.Now().Add(time.Duration(timeout) * time.Millisecond)
	C.pump(0, false)
	for {
		checkHidInterrupt()
		ready := darwinReady(states)
		remaining := time.Until(deadline)
		if len(ready) > 0 || remaining <= 0 {
			return ready
		}
		slice := min(remaining, 50*time.Millisecond)
		if C.pump(C.double(slice.Seconds()), true) == C.kCFRunLoopRunFinished {
			time.Sleep(min(slice, time.Until(deadline)))
		}
	}
}

func darwinReady(states []*C.HidDevice) []Value {
	var ready []Value
	for i, state := range states {
		if state.count != 0 || bool(state.removed) {
			ready = append(ready, int64(i))
		}
	}
	return ready
}

func (a *darwinHid) close(handle *hidDev) {
	if state := a.devices[handle]; state != nil {
		delete(a.devices, handle)
		delete(a.openIDs, handle.id)
		C.free_device(state)
	}
}
