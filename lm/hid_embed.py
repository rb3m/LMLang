"""Assemble the shared HID sources for standalone Python programs."""
from .hid_prims import OPS
from .pybackend_source import clean_source, wrap_module


def hid_runtime(directory):
    """Return source segments with the same primitive names as the Go target."""
    adapter = (directory / "hid_adapter.py").read_text(encoding="utf-8")
    darwin = (directory / "hid_darwin.py").read_text(encoding="utf-8")
    host = (directory / "hid_os.py").read_text(encoding="utf-8")
    replay = (directory / "hid_replay.py").read_text(encoding="utf-8")
    prims = (directory / "hid_prims.py").read_text(encoding="utf-8")
    segments = [
        clean_source(adapter),
        wrap_module(darwin, "hid_darwin"),
        clean_source(host),
        wrap_module(replay, "hid_replay"),
        "replay_hid = hid_replay.replay_hid",
        wrap_module(prims, "hid_prims"),
        """_hid_adapter = None

def _start_hid():
    global _hid_adapter
    _hid_adapter = hid_prims.start_hid()

def _close_hid():
    _hid_adapter.shutdown()""",
    ]
    for op in OPS:
        name = op.replace("-", "_")
        segments.append(f"def prim_hid_{name}(*args):\n"
                        f"    return hid_prims.hid_call(_hid_adapter, {op!r}, *args)")
    return segments
