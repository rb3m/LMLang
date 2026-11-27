"""Assemble the shared vinput sources for standalone Python programs."""
from .pybackend_source import clean_source, wrap_module
from .vinput_prims import VINPUT_OPS


def vinput_runtime(directory):
    adapter, linux, prims = ((directory / f"vinput_{name}.py").read_text(encoding="utf-8")
                             for name in ("adapter", "linux", "prims"))
    segments = [
        clean_source(adapter),
        wrap_module(linux, "vinput_linux"),
        wrap_module(prims, "vinput_prims"),
        """_vinput_adapter = None

def _start_vinput():
    global _vinput_adapter
    _vinput_adapter = vinput_prims.start_vinput(globals().get("_hid_adapter"))

def _close_vinput():
    _vinput_adapter.shutdown()""",
    ]
    for op in VINPUT_OPS:
        segments.append(f"def prim_vinput_{op}(*args):\n"
                        f"    return vinput_prims.vinput_call(_vinput_adapter, {op!r}, *args)")
    return segments
