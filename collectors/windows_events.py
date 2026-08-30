"""Windows Event Log collector.

Reads the ``System`` channel incrementally using the classic Event Log API
(``win32evtlog``) so we never rescan the whole log.  The last processed record
id and timestamp are persisted in the ``agent_state`` table so the cursor
survives service restarts.

Limitations (documented, not worked around with fragile hacks):
* Record ids are per-channel and can reset when a log is cleared.  We detect a
  regression and fall back to processing everything newer than the last seen
  timestamp.
* Process/thread id are generally not exposed by the classic API for these
  records and are left ``None``.
"""

from __future__ import annotations

import logging
import time

from collectors.base import BaseCollector

logger = logging.getLogger(__name__)

MAX_EVENTS_PER_RUN = 1000
MAX_MESSAGE_LEN = 4000

_STATE_KEY_ID = "event_last_record_id:{channel}"
_STATE_KEY_TS = "event_last_timestamp:{channel}"


class WindowsEventCollector(BaseCollector):
    name = "windows_events"

    def __init__(self, channel: str = "System"):
        self.channel = channel

    def collect(self, now: float, session_id: int, db=None) -> dict:
        if db is None:
            return {}
        last_id = self._int_or_none(db.get_state(_STATE_KEY_ID.format(channel=self.channel)))
        last_ts = self._float_or_none(db.get_state(_STATE_KEY_TS.format(channel=self.channel)))

        try:
            import win32evtlog
        except ImportError:
            logger.debug("pywin32 unavailable; skipping event collection")
            return {}

        records = self._read_new(win32evtlog, last_id or 0, last_ts or 0.0)
        if not records:
            return {}

        rows = []
        max_id = last_id or 0
        max_ts = last_ts or 0.0
        for rec in records:
            ts = _time_generated_to_epoch(rec)
            rows.append(
                {
                    "timestamp": ts,
                    "provider": getattr(rec, "SourceName", None),
                    "event_id": _normalize_event_id(getattr(rec, "EventID", None)),
                    "level": getattr(rec, "EventType", None),
                    "channel": self.channel,
                    "record_id": getattr(rec, "RecordNumber", None),
                    "message": _format_message(rec),
                    "computer": getattr(rec, "ComputerName", None),
                    "process_id": None,
                    "thread_id": None,
                }
            )
            max_id = max(max_id, getattr(rec, "RecordNumber", 0) or 0)
            max_ts = max(max_ts, ts)

        db.insert_events(rows, session_id)
        db.set_state(_STATE_KEY_ID.format(channel=self.channel), str(max_id))
        db.set_state(_STATE_KEY_TS.format(channel=self.channel), str(max_ts))
        return {}

    def _read_new(self, win32evtlog, last_id: int, last_ts: float) -> list:
        handle = None
        records: list = []
        try:
            handle = win32evtlog.OpenEventLog(None, self.channel)
            flags = (
                win32evtlog.EVENTLOG_BACKWARDS_READ
                | win32evtlog.EVENTLOG_SEQUENTIAL_READ
            )
            while len(records) < MAX_EVENTS_PER_RUN:
                batch = win32evtlog.ReadEventLog(handle, flags, 0)
                if not batch:
                    break
                stop = False
                for rec in batch:
                    rid = getattr(rec, "RecordNumber", 0) or 0
                    ts = _time_generated_to_epoch(rec)
                    if rid <= last_id and ts <= last_ts:
                        stop = True
                        break
                    records.append(rec)
                if stop:
                    break
        except Exception as exc:  # noqa: BLE001
            logger.warning("event log read failed: %s", exc)
        finally:
            if handle is not None:
                try:
                    win32evtlog.CloseEventLog(handle)
                except Exception:  # noqa: BLE001
                    pass
        records.reverse()
        return records

    @staticmethod
    def _int_or_none(value: str | None) -> int | None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _float_or_none(value: str | None) -> float | None:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None


def _normalize_event_id(raw) -> int | None:
    """Strip the high bit so IDs match classic log comparisons (e.g. 41, 6006)."""
    if raw is None:
        return None
    try:
        return int(raw) & 0xFFFF
    except (TypeError, ValueError):
        return None


def _time_generated_to_epoch(rec) -> float:
    t = getattr(rec, "TimeGenerated", None)
    if t is None:
        return time.time()
    try:
        return time.mktime(
            (t.year, t.month, t.day, t.hour, t.minute, t.second, 0, 0, -1)
        )
    except (ValueError, OverflowError, OSError):
        return time.time()


def _format_message(rec) -> str | None:
    try:
        import win32evtlogutil

        return win32evtlogutil.SafeFormatMessage(rec, "System")[:MAX_MESSAGE_LEN]
    except Exception:  # noqa: BLE001
        inserts = getattr(rec, "StringInserts", None)
        if inserts:
            return " | ".join(str(s) for s in inserts)[:MAX_MESSAGE_LEN]
        return None
