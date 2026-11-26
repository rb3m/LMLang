# macOS HID live checklist

Run from the repository root in a local terminal with `LM_HID_REPLAY` unset.

1. Build and list the attached devices. Check that IDs are sorted and that a device keeps its ID across two runs while it stays attached.

   ```sh
   bin/lm build hid-monitor.main examples/hid-monitor/hid-monitor.lm -o /tmp/hid-monitor
   /tmp/hid-monitor
   ```

2. Run `/tmp/hid-monitor DEVICE-ID` with an external mouse's ID. Move it and check that reports appear as an ID and a hexadecimal payload. Unplug the mouse and check that the monitor drains any queued reports and exits. Repeat with a `--target py` build to check the Python runtime.
3. For a keyboard, open the selected device and check that macOS requests Input Monitoring if access is missing. Grant it in System Settings → Privacy & Security → Input Monitoring for the terminal or executable named by macOS, then relaunch and type a few test keys.
4. With a spare external mouse and another pointing device available, call `hid.grab d true` in a test entry that keeps reading the mouse. Check that reports continue while the desktop ignores the mouse. Call `hid.grab d false` and verify that desktop input resumes. Repeat and close the handle or exit the entry while grabbed to verify release. Use a mouse only for this step.
