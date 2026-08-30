"""Heartbeat file helpers.

The authoritative heartbeat lives in the SQLite database; an on-disk file is
also written as a lightweight secondary signal that a technician (or a future
external watchdog) can inspect without opening the database.
"""

from __future__ import annotations

import os


def write_heartbeat_file(path: str, timestamp: float) -> None:
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(str(timestamp))
    except OSError:
        pass


def read_heartbeat_file(path: str) -> float | None:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return float(handle.read().strip())
    except (OSError, ValueError):
        return None
