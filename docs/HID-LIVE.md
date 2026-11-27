# HID live checklist

## macOS

Run from the repository root in a local terminal with `LM_HID_REPLAY` unset.

1. Build and list the attached devices. Check that IDs are sorted and that a device keeps its ID across two runs while it stays attached.

   ```sh
   bin/lm build hid-monitor.main examples/hid-monitor/hid-monitor.lm -o /tmp/hid-monitor
   /tmp/hid-monitor
   ```

2. Run `/tmp/hid-monitor DEVICE-ID` with an external mouse's ID. Move it and check that reports appear as an ID and a hexadecimal payload. Unplug the mouse and check that the monitor drains any queued reports and exits. Repeat with a `--target py` build to check the Python runtime.
3. For a keyboard, open the selected device and check that macOS requests Input Monitoring if access is missing. Grant it in System Settings → Privacy & Security → Input Monitoring for the terminal or executable named by macOS, then relaunch and type a few test keys.
4. With a spare external mouse and another pointing device available, call `hid.grab d true` in a test entry that keeps reading the mouse. Check that reports continue while the desktop ignores the mouse. Call `hid.grab d false` and verify that desktop input resumes. Repeat and close the handle or exit the entry while grabbed to verify release. Use a mouse only for this step.

## Linux

Run from the repository root in a local terminal with `LM_HID_REPLAY` unset.

1. Build and list the attached devices. Check that IDs are sorted, start with `linux:`, and stay stable across two runs while the devices remain attached. Check that the USB interface number matches sysfs.

   ```sh
   bin/lm build hid-monitor.main examples/hid-monitor/hid-monitor.lm -o /tmp/hid-monitor-linux
   file /tmp/hid-monitor-linux
   /tmp/hid-monitor-linux
   ```

2. Run `/tmp/hid-monitor-linux DEVICE-ID` for a spare external mouse or controller. Generate input and check the report IDs and hexadecimal payloads against the device descriptor. Unplug it during a wait and check that the monitor drains queued reports before reporting `disconnected`. Repeat with a `--target py` build and the interpreter.
3. With a device that documents a readable feature report, call `hid.feature-get d id length` in a test entry and compare the returned bytes to the documented payload. Use ID 0 for an unnumbered feature report. If access is denied, check the udev rules or ACLs for the hidraw node and repeat with a read/write handle.
4. With a spare external mouse and another pointing device available, call `hid.grab d true` in a test entry that keeps reading the mouse. Check that reports continue while the desktop ignores the mouse. Call `hid.grab d false` and check that desktop input resumes. Repeat while closing the handle and while interrupting a wait with SIGINT or SIGTERM. If running under systemd, verify that the service account can open the hidraw node and all of the device's sibling evdev nodes before testing the grab.
