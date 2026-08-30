"""Boot / session detection.

On every startup a new ``sessions`` row is created and the previous session is
finalised with its shutdown outcome, using multiple independent sources of
evidence from the Windows Event Log rather than a single event.
"""

from __future__ import annotations

import logging

from diagnostics import event_analyzer

logger = logging.getLogger(__name__)


def detect_boot(db, now: float, boot_time: float | None = None) -> dict:
    if boot_time is None:
        try:
            import psutil

            boot_time = psutil.boot_time()
        except Exception:
            boot_time = now

    prev = db.latest_session()
    previous_boot_time = prev["boot_time"] if prev else None
    previous_session_id = prev["session_id"] if prev else None

    result: dict = {
        "boot_time": boot_time,
        "previous_boot_time": previous_boot_time,
        "previous_session_id": previous_session_id,
        "previous_session_clean": None,
        "unexpected_shutdown": False,
        "kernel_power_detected": False,
        "bugcheck_detected": False,
        "uptime_before_boot": None,
    }

    if prev is not None and boot_time is not None and abs(prev["boot_time"] - boot_time) < 60.0:
        # Same OS boot as the latest session: this is a service restart, not a
        # reboot.  Reuse the existing session and carry its boot metadata so no
        # duplicate session or spurious incident is created.
        result["session_id"] = prev["session_id"]
        result["previous_boot_time"] = prev["previous_boot_time"]
        earlier = db.query(
            "SELECT session_id FROM sessions WHERE session_id < ? ORDER BY session_id DESC LIMIT 1",
            (prev["session_id"],),
        )
        result["previous_session_id"] = earlier[0]["session_id"] if earlier else None
        result["previous_session_clean"] = (
            None if prev["previous_session_clean"] is None else bool(prev["previous_session_clean"])
        )
        result["unexpected_shutdown"] = bool(prev["unexpected_shutdown"])
        result["kernel_power_detected"] = bool(prev["kernel_power_detected"])
        result["bugcheck_detected"] = bool(prev["bugcheck_detected"])
        result["uptime_before_boot"] = prev["uptime_before_boot"]
        return result

    if prev is not None and previous_boot_time:
        # Events describing this transition are written around the new boot;
        # allow a small margin after boot so Kernel-Power 41 / BugCheck 1001 /
        # 6008 (all stamped at boot) are included.
        end = boot_time + 120.0
        events = _events_between(db, previous_boot_time, end)
        summary = event_analyzer.summarize(events)

        clean = summary["clean_shutdown"]
        kp41 = summary["kernel_power_detected"]
        bugcheck = summary["bugcheck_detected"]
        unexpected = summary["unexpected_shutdown_event"]

        result["previous_session_clean"] = clean
        result["kernel_power_detected"] = kp41
        result["bugcheck_detected"] = bugcheck
        result["unexpected_shutdown"] = (not clean) and (kp41 or unexpected)
        result["uptime_before_boot"] = boot_time - previous_boot_time

        db.update_session(
            previous_session_id,
            previous_session_clean=1 if clean else 0,
            unexpected_shutdown=1 if result["unexpected_shutdown"] else 0,
            kernel_power_detected=1 if kp41 else 0,
            bugcheck_detected=1 if bugcheck else 0,
            uptime_before_boot=result["uptime_before_boot"],
        )

    session_id = db.create_session(boot_time, now)
    if previous_boot_time is not None:
        db.update_session(session_id, previous_boot_time=previous_boot_time)
    result["session_id"] = session_id
    return result


def _events_between(db, start: float, end: float) -> list[dict]:
    rows = db.query(
        "SELECT * FROM events WHERE timestamp >= ? AND timestamp <= ? ORDER BY timestamp",
        (start, end),
    )
    return [dict(r) for r in rows]
