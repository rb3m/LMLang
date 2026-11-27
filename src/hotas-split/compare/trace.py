"""Shared HOTAS constants and helpers for LM HID replay traces."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENDOR = 0x044F
PRODUCT = 0xB68D
DEVICE = {
    "id": "hotas",
    "vendor": VENDOR,
    "product": PRODUCT,
    "usage-page": 1,
    "usage": 4,
    "interface": -1,
    "name": "T.Flight Hotas One",
    "serial": "",
}


def trace(packets):
    """Store numbered HID packets with the report ID outside the payload."""
    events = [
        {"at-ms": at, "dev": DEVICE["id"],
         "report-id": packet[0], "data": packet[1:].hex()}
        for at, packet in packets
    ]
    end = events[-1]["at-ms"] + 1 if events else 1
    events.append({"at-ms": end, "dev": DEVICE["id"], "unplug": True})
    return {"devices": [DEVICE], "events": events}


def write_trace(path, recording):
    """Keep each input report on its own line for readable diffs."""
    events = ",\n".join("    " + json.dumps(event) for event in recording["events"])
    devices = json.dumps(recording["devices"])
    path.write_text(
        f'{{\n  "devices": {devices},\n  "events": [\n{events}\n  ]\n}}\n',
        encoding="utf-8",
    )
