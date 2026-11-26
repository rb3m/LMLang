# HID monitor

Run from the repository root. The project declares `(ext hid)` in `lm.deps`.

```sh
bin/lm test examples/hid-monitor
LM_HID_REPLAY=/path/to/trace.json bin/lm run hid-monitor.main --allow hid.io --allow io.in --allow io.out
LM_HID_REPLAY=/path/to/trace.json bin/lm run hid-monitor.main --allow hid.io --allow io.in --allow io.out -- DEVICE-ID
```

The first replay command lists the attached device IDs and names. The second
prints the selected device's report IDs and hexadecimal payloads until it
disconnects or you interrupt the program. P2a uses trace files for input and
reports `unsupported` through the OS adapter.
