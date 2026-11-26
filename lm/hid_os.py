"""Select the host HID adapter."""
import sys
import time

from .hid_adapter import UnavailableHid


class UnsupportedHid(UnavailableHid):
    def __init__(self):
        super().__init__("unsupported")

    def invoke(self, op, *args):
        if op == "wait" and not args[0]:
            time.sleep(args[1] / 1000)
            return ()
        return super().invoke(op, *args)


def os_hid():
    if sys.platform == "darwin":
        from . import hid_darwin
        return hid_darwin.DarwinHid()
    return UnsupportedHid()
