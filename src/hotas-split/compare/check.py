#!/usr/bin/env python3
"""Compare LM replay frames with the original Python bridge, without devices."""

import argparse
from itertools import zip_longest
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace

from trace import PRODUCT, ROOT, VENDOR

# Import the original read-only. It imports evdev only from its live entry point.
sys.dont_write_bytecode = True
from hotas_split import config, device  # noqa: E402

PROJECT = ROOT.parent
LM = PROJECT.parent.parent / "bin/lm"
AXIS_CODES = {
    0: "x", 1: "y", 2: "z", 3: "rx", 4: "ry", 5: "rz",
    6: "throttle", 7: "rudder", 8: "wheel", 9: "gas", 10: "brake",
}
CODES = SimpleNamespace(
    EV_ABS=3, EV_KEY=1, BTN_TRIGGER=0x120, ABS_HAT0X=16, ABS_HAT0Y=17,
    **{f"ABS_{name.upper()}": code for code, name in AXIS_CODES.items()},
)
EFFECTS = ("env.read", "fs.read", "hid.io", "hid.grab", "io.in", "io.out",
           "vinput.emit")
RUNTIMES = ("interpreter", "python", "go")


def selected_device(trace):
    return next((dev for dev in trace["devices"]
                 if (dev["vendor"], dev["product"]) == (VENDOR, PRODUCT)), None)


def input_reports(trace, match):
    """Yield reports for the same first matching device selected by LM."""
    if match is None:
        return
    for event in sorted(trace["events"], key=lambda item: item["at-ms"]):
        if event["dev"] != match["id"]:
            continue
        if event.get("unplug") is True:
            return
        if "report-id" in event:
            yield event["at-ms"], bytes([event["report-id"]]) + bytes.fromhex(event["data"])
    raise ValueError("trace must end with an unplug for the selected HOTAS")


class ReplayEnded(OSError):
    """Simulate the Python hidraw read error after the last report."""


class FakeSource:
    def __init__(self, reports):
        self.reports = enumerate(reports, 1)
        self.number = self.at = self.report = None

    def read(self, _count):
        try:
            self.number, (self.at, self.report) = next(self.reports)
        except StopIteration:
            raise ReplayEnded("hidraw device disconnected") from None
        # Replay preserves the wire packet, including intentionally oversized
        # synthetic packets used by the pure report decoder tests.
        return self.report


class FakeUInput:
    """Capture Python writes and translate them to vinput's control model."""

    def __init__(self, source):
        self.source = source
        self.frames = []
        self.axes = []
        self.buttons = [False] * 15
        self.button_changes = []
        self.hat = [0, 0]
        self.previous_hat = tuple(self.hat)

    def write(self, event_type, code, value):
        if event_type == CODES.EV_KEY:
            index = code - CODES.BTN_TRIGGER
            pressed = bool(value)
            if self.buttons[index] != pressed:
                self.button_changes.append(["button", index, pressed])
            self.buttons[index] = pressed
            return
        if code in (CODES.ABS_HAT0X, CODES.ABS_HAT0Y):
            self.hat[code - CODES.ABS_HAT0X] = value
            return
        self.axes.append(["axis", AXIS_CODES[code], value])

    def syn(self):
        changes = self.axes + self.button_changes
        current_hat = tuple(self.hat)
        if current_hat != self.previous_hat:
            changes.append(["hat", 0, *current_hat])
        self.frames.append(
            (self.source.number, self.source.at, self.source.report.hex(), changes)
        )
        self.axes.clear()
        self.button_changes.clear()
        self.previous_hat = current_hat


def python_config(path, directory):
    if path is None or not path.exists():
        return config.Config()
    settings = json.loads(path.read_text(encoding="utf-8"))
    lines = [
        f"{key} = {json.dumps(value, ensure_ascii=False)}"
        for key, value in settings.items() if not isinstance(value, dict)
    ]
    for table, fields in settings.items():
        if not isinstance(fields, dict):
            continue
        lines.append(f"[{table}]")
        lines.extend(f"{key} = {json.dumps(value, ensure_ascii=False)}"
                     for key, value in fields.items())
    toml = directory / "config.toml"
    toml.write_text("\n".join(lines), encoding="utf-8")
    return config.load_config(toml)


def python_frames(trace, match, settings):
    source = FakeSource(input_reports(trace, match))
    output = FakeUInput(source)
    try:
        device._loop(source, output, CODES, settings)
    except ReplayEnded:
        return output.frames


def run_lm(command, trace_path, config_path, directory, timeout):
    log = directory / "frames.jsonl"
    log.unlink(missing_ok=True)
    env = dict(os.environ, HOME=str(directory), LM_HID_REPLAY=str(trace_path),
               LM_HID_REPLAY_LOG=str(log), PYTHONDONTWRITEBYTECODE="1")
    args = ["--config", str(config_path)] if config_path else []
    result = subprocess.run(
        [*command, *args], env=env, cwd=PROJECT, text=True, capture_output=True,
        timeout=timeout, check=False,
    )
    if result.returncode != 0 or "Cannot load configuration:" in result.stderr:
        raise ValueError(f"exit {result.returncode}: {result.stderr.strip()}")
    if not log.exists():
        return []
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]


def comparable_events(events):
    """A frame is atomic; compare per-control values independently of write order."""
    return sorted(events, key=lambda event: (event[0], event[1]))


def compare(expected, recorded, match, settings):
    frames = [event for event in recorded if event["op"] == "vinput-frame"]
    for frame_number, (want, got) in enumerate(zip_longest(expected, frames), 1):
        if want is None:
            return f"unexpected frame {frame_number} after last valid report: {got}"
        number, at, packet, events = want
        actual = None if got is None else comparable_events(got["events"])
        if comparable_events(events) != actual:
            return (f"first difference at report {number} ({at} ms, {packet}), "
                    f"frame {frame_number}\n  Python: {events}\n  LM: {got}")
    return compare_lifecycle(recorded, match, settings)


def compare_lifecycle(recorded, match, settings):
    actions = [event for event in recorded if event["op"] != "vinput-frame"]
    if match is None:
        return f"unexpected actions without a HOTAS: {actions}" if actions else None
    expected_ops = ["grab", "vinput-create", "vinput-close", "close"]
    if [event["op"] for event in actions] != expected_ops:
        return f"unexpected device lifecycle: {actions}"
    grab, create, close_output, close_input = actions
    if not grab["on"] or grab["dev"] != match["id"] or close_input["dev"] != match["id"]:
        return f"unexpected HID lifecycle: {grab}, {close_input}"
    if close_output["dev"] != create["dev"]:
        return f"unexpected joystick close: {close_output}"
    expected_axes = [
        {"name": name, "min": 0, "max": maximum}
        for name, maximum in (
            ("x", 1023), ("y", 1023), ("z", 255),
            (AXIS_CODES[getattr(CODES, settings.twist_axis)], 1023),
            (AXIS_CODES[getattr(CODES, settings.rocker_axis)], 1023),
        )
    ]
    if (create["name"], create["axes"], create["buttons"], create["hats"]) != (
            "T.Flight Hotas One (split)", expected_axes, 15, 1):
        return f"unexpected joystick capabilities: {create}"
    return None


def check_trace(path, args, directory):
    config_path = args.config
    if config_path is None:
        sidecar = path.with_suffix(".config.json")
        if sidecar.is_file():
            config_path = sidecar
    try:
        trace = json.loads(path.read_text(encoding="utf-8"))
        match = selected_device(trace)
        settings = python_config(config_path, directory)
        expected = python_frames(trace, match, settings)
    except (OSError, KeyError, ValueError) as error:
        print(f"{path.name}: {error}", file=sys.stderr)
        return False
    commands = {
        "interpreter": [str(LM), "run", "hotas-split.main",
                        *(arg for effect in EFFECTS for arg in ("--allow", effect)), "--"],
        "python": [str(args.py_build)],
        "go": [str(args.go_build)],
    }
    passed = True
    for runtime in args.runtime or RUNTIMES:
        try:
            recorded = run_lm(commands[runtime], path, config_path, directory, args.timeout)
            difference = compare(expected, recorded, match, settings)
        except (OSError, ValueError, subprocess.TimeoutExpired) as error:
            difference = str(error)
        if difference:
            print(f"{runtime} {path.name}: FAIL\n  {difference}", file=sys.stderr)
            passed = False
            continue
        print(f"{runtime} {path.name}: {len(expected)} frames, 0 mismatches", flush=True)
    return passed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("traces", metavar="TRACE", nargs="*", type=Path)
    parser.add_argument("--py-build", type=Path, default=PROJECT / "build/hotas-split.py")
    parser.add_argument("--go-build", type=Path, default=PROJECT / "build/hotas-split")
    parser.add_argument("--runtime", choices=RUNTIMES, action="append")
    parser.add_argument("--config", type=Path, help="LM JSON settings for all traces")
    parser.add_argument("--timeout", type=float, default=120, help="Seconds per LM run")
    args = parser.parse_args()
    for name in ("py_build", "go_build", "config"):
        path = getattr(args, name)
        if path is not None:
            setattr(args, name, path.resolve())
    paths = args.traces or sorted(
        path for path in (ROOT / "traces").glob("*.json")
        if not path.name.endswith(".config.json")
    )
    with tempfile.TemporaryDirectory(prefix="hotas-compare-") as scratch:
        results = [check_trace(path.resolve(), args, Path(scratch)) for path in paths]
    return int(not all(results))


if __name__ == "__main__":
    sys.exit(main())
