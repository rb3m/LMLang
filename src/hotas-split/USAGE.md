# T.Flight Hotas One split bridge

The bridge matches USB device `044f:b68d`, grabs it through `ext/hid`, and
creates **T.Flight Hotas One (split)** through `ext/vinput`. It forwards X, Y,
the throttle lever, the hat and all 15 buttons. It assigns the separate twist
and rocker sensor words to Rz and Rx by default. Calibration uses a fixed
centre and widens each range until the device disconnects.

## Build and run

From `src/hotas-split/` with Go on your PATH:

```sh
mkdir -p build
../../bin/lm check
../../bin/lm test
PATH="$HOME/.local/go/bin:$PATH" ../../bin/lm build hotas-split.main -o build/hotas-split
../../bin/lm build hotas-split.main --target py -o build/hotas-split.py
```

On Linux, with existing access to the matching HID device and `/dev/uinput`,
run `./build/hotas-split`. An absent HOTAS or an unplug exits with status 0
and a message on stderr. In replay, both builds closed the HID and virtual
joystick handles on SIGTERM and exited with status 143.

To switch an existing systemd **user** service, the owner would set
`ExecStart` to the absolute path of the Go binary. For a user-unit drop-in,
clear the previous command first. Keep `Restart=no` so a later plug-in can
start the service through the existing udev rule. The example path uses
systemd's `%h` expansion for the user's home directory.

```ini
[Service]
ExecStart=
ExecStart=%h/path/to/LMLang/src/hotas-split/build/hotas-split
Restart=no
SuccessExitStatus=143
```

## JSON configuration

The optional file is `~/.config/hotas-split/config.json`. Use
`--config PATH` to select a different JSON file. A missing file uses the
measured defaults.

```json
{
  "deadzone_percent": 12.5,
  "twist": {"min": 1000, "max": 7700, "centre": 4300, "invert": false},
  "rocker": {"min": 1200, "max": 7000, "centre": 4170, "invert": true, "deadzone_percent": 12},
  "axes": {"twist": "ABS_RZ", "rocker": "ABS_RX"}
}
```

A per-axis `deadzone_percent` overrides the shared value. Without either
override, twist uses 13% and rocker 12%. The percentage must be a number
in `[0, 100)`. Each axis requires integer `min < centre < max` and a boolean
`invert`. For an inverted axis, the calibration coordinates refer to
`8191 - raw`. Output names must differ and can be `ABS_RX`, `ABS_RY`,
`ABS_RZ`, `ABS_THROTTLE`, `ABS_RUDDER`, `ABS_WHEEL`, `ABS_GAS` or
`ABS_BRAKE`. Invalid config exits with status 2. Calibration integers in
LM JSON are signed 64-bit.

## Replay comparison

Build both targets as above, then run the comparison against the checked-in
synthetic traces:

```sh
PYTHONPATH="$HOME/Code/hotas-split/src" python3 compare/check.py
```

The comparator drives the original Python `device._loop` with fake hidraw
and uinput objects. For each valid report it compares that report's Python
sync with the corresponding LM replay frame, including empty syncs. It
groups the two hat coordinates into one hat update and accounts for vinput
starting with neutral hats and released buttons. Frame order and control
changes are checked. Timing comes from the host replay clock and may vary.
The first mismatch shows the input report number and payload. Pass
`--runtime interpreter`, `--runtime python` or `--runtime go` to select a
runtime. `--py-build` and `--go-build` can point to other build paths.

`python3 compare/generate.py` regenerates the synthetic traces. Config
sidecars such as `ties.config.json` apply to both programs for that trace.
Use `--config PATH` to explicitly select settings for a comparison.

### Record a hardware trace

The owner or coordinator can run this on the Linux workstation with the
HOTAS plugged in and read access to its hidraw node:

```sh
./compare/record /tmp/hotas-recorded.json --seconds 30
PYTHONPATH="$HOME/Code/hotas-split/src" python3 compare/check.py /tmp/hotas-recorded.json
```

Move both sensors slowly through their full travel, release each to centre,
then move the stick and throttle, turn the hat and tap each button. The
recorder reads input reports by identifying the HOTAS in sysfs. Press
Ctrl+C, unplug, or let the timer expire. It writes an `LM_HID_REPLAY` JSON
file with one device, relative millisecond timestamps, a separate report ID
and hex payload for each packet, and a final unplug event. Replay uses
`LM_HID_REPLAY_LOG` for virtual joystick output and does not need hardware.
