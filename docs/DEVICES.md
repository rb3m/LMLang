# Using your own devices

How to make LM work with a HID device you own: a gamepad, pedals, a keypad, a stream deck, an LED controller. The toolchain itself needs no changes. LM's device modules are generic. Everything that knows about one particular device lives in a program you write. `src/hotas-split/` is a complete example for one joystick.

Read `docs/SPEC.md` ("HID extension" and "vinput extension") for the exact rules. This page is the route through them.

## What works today

| | Linux | macOS | Windows |
|---|---|---|---|
| `hid`: list devices, read input reports, write output reports, feature reports | yes | yes | no |
| `hid.grab`: stop the OS and other apps from seeing the device | yes (evdev grab) | yes (seize) | no |
| `vinput`: create a virtual joystick | yes (uinput) | no (needs a signed DriverKit extension) | no |

All three runtimes behave the same: the interpreter (`lm run`), the Python build (`lm build --target py`) and the Go build (`lm build`, static on Linux).

Limits:
- Only HID devices: anything that appears as `/dev/hidraw*` on Linux or in IOKit's HID Manager on macOS. Serial ports, MIDI devices and devices that need a vendor driver are out of scope.
- `vinput` makes joysticks only: axes named `x y z rx ry rz throttle rudder wheel gas brake`, up to 56 buttons, up to 4 hats. No virtual keyboard or mouse, no relative axes, no force feedback.
- Verified live with USB devices. Bluetooth HID devices also appear through hidraw, but they have not been tested.

Supporting another OS or another kind of output means adding an adapter or extending `vinput`. See ADR-083 (`docs/decisions/0083-device-io-layered-hid-vinput.md`) before proposing either.

## 1. Give your user access (Linux, once, needs sudo)

Most distributions make `/dev/hidraw*` readable only by root. Find your device's IDs with `lsusb` (for example `1234:abcd`), then create `/etc/udev/rules.d/70-my-device.rules`:

```
# Read and write the raw HID node.
SUBSYSTEM=="hidraw", ATTRS{idVendor}=="1234", ATTRS{idProduct}=="abcd", TAG+="uaccess"
# Only needed for hid.grab: the device's evdev nodes.
SUBSYSTEM=="input", ATTRS{idVendor}=="1234", ATTRS{idProduct}=="abcd", TAG+="uaccess"
```

For `vinput` you also need write access to `/dev/uinput`. Some distributions grant it already (Fedora does through Steam's input rules). Check with `ls -l /dev/uinput`: a `+` after the permissions means an access list is set. If your user has no access, add:

```
KERNEL=="uinput", SUBSYSTEM=="misc", TAG+="uaccess", OPTIONS+="static_node=uinput"
```

Use lowercase hexadecimal IDs. Keep the number below 73, because `uaccess` is applied by a later rules file. Then run `sudo udevadm control --reload && sudo udevadm trigger`, or unplug and replug the device. A `permission` error from `hid.open` or `vinput.create` means this step is missing.

On macOS, mice, joysticks and gamepads need no setup. Keyboards need Input Monitoring: the first `hid.open` fails with `permission` and macOS prompts. Grant access under System Settings → Privacy & Security → Input Monitoring, then run again.

## 2. Find your device and learn its reports

Build the monitor and list what is attached:

```sh
bin/lm build hid-monitor.main examples/hid-monitor/hid-monitor.lm -o /tmp/hid-monitor
/tmp/hid-monitor
/tmp/hid-monitor DEVICE-ID
```

The first command prints every device's ID and name. Each ID lasts while the device stays plugged in. Programs should find a device by vendor and product (fields of `hid.Info`), not by a saved ID. The second command prints each report as a report ID and a hexadecimal payload. LM strips the report-ID byte, so payload offsets start after it.

Press one control at a time and note which bytes change and how: a 16-bit little-endian axis, a bit per button, a 4-bit hat. Write it down as a table, for example "bytes 17-18: twist, little-endian, 0..8191". The next step needs that table. Some devices have several report IDs, or several interfaces that show up as separate device IDs with the same vendor and product. Check each one.

## 3. Write the program

```sh
bin/lm new my-bridge        # creates a project with its own AGENTS.md
cd my-bridge
```

Opt in to the extensions in `lm.deps`:

```
(deps
  (ext hid)
  (ext vinput))
```

Then follow the shape of `src/hotas-split/`:

- **Decode:** a pure function from `hid.Report` to your own record type, using `bytes` getters (`bytes.u8`, `bytes.u16le`, `bytes.s16le` and friends; `lm index --stdlib --module bytes`). Give it examples built from bytes you captured in step 2.
- **Transform:** calibration, deadzones, remapping. Keep it pure, with examples.
- **Loop:** find the device with `hid.enumerate`, `hid.open` it, optionally `hid.grab` it, `vinput.create` a joystick, then repeat `hid.wait` → `hid.read` → `vinput.axis`/`button`/`hat` → `vinput.sync`. `sync` sends only what changed. Catch `hid.HidError` with message `disconnected` to exit cleanly on unplug. On exit, fault or SIGTERM, the runtime releases grabs and destroys virtual devices, so no button stays pressed.

Other output is possible without `vinput`: `hid.write` sends output reports, and `hid.feature-set` sends feature reports (LEDs, modes). Check what your device documents before writing to it. A wrong feature report can change device settings.

Effects: `hid.io` covers reading and writing reports, `hid.grab` covers grabbing, and `vinput.emit` covers injecting input. With `lm run`, allow each one explicitly, for example `--allow hid.io --allow hid.grab --allow vinput.emit`. Run `lm index --module hid` and `lm index --module vinput` for the signatures and notes.

## 4. Test without the device

- **Examples:** `(given (hid (device ..) (report ..) (unplug ..)))` scripts a device, and `(hid-log ..)` and `(vinput-log ..)` check what your function sent. Time is virtual, so timed loops run instantly. `examples/hid-monitor/` and `examples/vinput-demo/` show the forms. The module notes list every clause.
- **Replay:** record a real session as a JSON trace, then run any runtime with `LM_HID_REPLAY=trace.json LM_HID_REPLAY_LOG=out.jsonl`. The program sees the recorded device and reports instead of the OS, and the log lists everything it wrote, grabbed or sent to `vinput`. `src/hotas-split/compare/record` is a recorder you can adapt. The trace format is in SPEC's "HID extension" section and `tests/conformance/hid/*.json`.
- **Comparing with an existing tool:** `src/hotas-split/compare/check.py` drives an older Python bridge and the LM port with the same trace and compares their output frame by frame. Use the same approach when replacing a working tool.

## 5. Run it as a service (Linux)

Build the Go binary (`lm build my-bridge.main -o my-bridge`). It is static and needs no Python. Start it from a systemd user unit. To start it automatically when the device is plugged in, add `TAG+="systemd", ENV{SYSTEMD_USER_WANTS}+="my-bridge.service"` to the hidraw rule from step 1. `src/hotas-split/USAGE.md` shows a complete unit. A stop by SIGTERM exits with status 143 after cleanup.

## When something fails

| Error category | Usual cause |
|---|---|
| `permission` | Step 1 missing for this node (Linux), or Input Monitoring not granted (macOS keyboards) |
| `not-found` | Device unplugged or the ID changed. Look it up again with `hid.enumerate` |
| `busy` | Another program grabbed the device (often a running bridge or Steam Input), or the same program opened it twice |
| `unsupported` | Not available on this OS (`vinput` on macOS, anything on Windows), no `/dev/uinput`, or a device with no evdev nodes to grab |
| `disconnected` | Unplugged. Queued reports are delivered first |
| `invalid-request` | An argument out of range: report ID, payload length, axis value, button index |
