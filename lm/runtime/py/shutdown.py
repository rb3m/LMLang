"""Signal shutdown shared by lm run and generated Python programs."""
import os
import signal
import sys


class _RunInterrupted(BaseException):
    pass


def _flush_standard_streams():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.flush()
        except (OSError, ValueError):
            pass


def run_with_signal_shutdown(run, runtime):
    received = None
    running = True
    flushed = False
    previous = {}

    def interrupt(signum, frame):
        nonlocal received
        if received is not None:
            return
        received = signum
        if running:
            raise _RunInterrupted

    try:
        for signum in (signal.SIGTERM, signal.SIGINT):
            previous[signum] = signal.signal(signum, interrupt)
        with runtime:
            try:
                return run()
            finally:
                running = False
                if received is not None:
                    _flush_standard_streams()
                    flushed = True
    finally:
        if received is not None:
            if not flushed:
                _flush_standard_streams()
            # The program thread may still be running after its devices are closed.
            os._exit(128 + received)
        for signum, handler in previous.items():
            signal.signal(signum, handler)
