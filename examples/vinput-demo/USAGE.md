# Virtual joystick demo

Run from the repository root. The project enables the extension with
`(ext vinput)` in `lm.deps`.

```sh
bin/lm test examples/vinput-demo
bin/lm run vinput-demo.main --allow vinput.emit
bin/lm build vinput-demo.main --os linux -o /tmp/vinput-demo
```

The live program needs write access to Linux's `/dev/uinput`. It creates
**LM Virtual Joystick**, sends five X positions, taps button zero, then destroys
the device. The example checks the same frames against an in-memory log.

To record a run on any platform, point replay at an empty HID trace and choose a
JSON Lines output file. The recorder appends to the file.

```sh
printf '%s\n' '{"devices":[],"events":[]}' > /tmp/vinput-trace.json
LM_HID_REPLAY=/tmp/vinput-trace.json LM_HID_REPLAY_LOG=/tmp/vinput.jsonl \
  bin/lm run vinput-demo.main --allow vinput.emit
```
