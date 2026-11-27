"""Append a device replay entry to the shared JSON Lines log."""
import json


def replay_log_writer(log_path):
    def append(row):
        if log_path is not None:
            with open(log_path, "a", encoding="utf-8") as stream:
                stream.write(json.dumps(row, ensure_ascii=False) + "\n")

    return append
