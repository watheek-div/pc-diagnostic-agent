"""Timestamp helpers.

All timestamps are stored internally as UTC epoch seconds (float).  Display
code converts to the local timezone when producing reports or CLI output.
"""

from __future__ import annotations

import datetime as _dt
import time


def now() -> float:
    return time.time()


def utc_from_epoch(epoch: float) -> _dt.datetime:
    return _dt.datetime.fromtimestamp(epoch, tz=_dt.timezone.utc)


def local_from_epoch(epoch: float) -> _dt.datetime:
    # Convert via an aware UTC datetime first: calling fromtimestamp() without
    # a timezone can raise OSError on Windows for pre-1970 or out-of-range
    # values, whereas UTC -> local conversion is pure offset arithmetic.
    return _dt.datetime.fromtimestamp(epoch, tz=_dt.timezone.utc).astimezone()


def format_local(epoch: float, fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
    if epoch is None:
        return "n/a"
    return local_from_epoch(epoch).strftime(fmt)


def format_clock(epoch: float) -> str:
    return format_local(epoch, "%H:%M:%S")


def epoch_from_datetime(value: _dt.datetime) -> float:
    if value.tzinfo is None:
        value = value.replace(tzinfo=_dt.timezone.utc)
    return value.timestamp()
