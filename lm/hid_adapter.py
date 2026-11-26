"""HID adapter contract, shared validation and opaque device identity."""
from __future__ import annotations

import re

CAPS = frozenset(("enumerate", "read", "write", "feature", "grab"))
INFO_FIELDS = ("id", "vendor", "product", "usage-page", "usage", "interface",
               "name", "serial")
MAX_TIMEOUT = 3_600_000
MAX_LENGTH = 4096
MAX_QUEUE = 1024


class HidProblem(Exception):
    def __init__(self, device, category):
        super().__init__(device, category)
        self.device = device
        self.category = category


class HidDev:
    def __init__(self, device):
        self.id = device


def valid_int(value, minimum, maximum):
    return type(value) is int and minimum <= value <= maximum


def report_id(value):
    return valid_int(value, 0, 255)


def report_length(value):
    return valid_int(value, 1, MAX_LENGTH)


def decode_report(data):
    if (not isinstance(data, str) or len(data) % 2
            or not report_length(len(data) // 2)
            or re.fullmatch(r"[0-9a-fA-F]+", data) is None):
        raise ValueError("expected 1..4096 bytes in hexadecimal")
    return bytes.fromhex(data)


class UnavailableHid:
    """Adapter for an unsupported OS or an unreadable/malformed replay."""

    def __init__(self, category):
        self.category = category

    def supports(self, cap):
        return False

    def invoke(self, op, *args):
        if op == "supports":
            return self.supports(args[0])
        device = args[0] if op == "open" else ""
        raise HidProblem(device, self.category)

    def shutdown(self):
        pass
