"""Crash (BSOD / BugCheck / Kernel-Power) detection.

Pure functions over event summaries and boot signals so they are trivially
testable without touching real hardware.
"""

from __future__ import annotations


def detect_crash(summary: dict, previous_session_clean: bool | None) -> dict:
    """Classify the previous session termination into discrete signals.

    Returns a dict of booleans.  These are *signals*, not root causes.
    """
    bugcheck = bool(summary.get("bugcheck_detected"))
    kernel_power = bool(summary.get("kernel_power_detected"))
    unexpected = bool(summary.get("unexpected_shutdown_event"))
    clean = bool(previous_session_clean)

    return {
        "bugcheck_detected": bugcheck,
        "kernel_power_detected": kernel_power,
        "unexpected_shutdown_event": unexpected,
        "clean_shutdown": clean,
        "unexpected_shutdown": (not clean) and (kernel_power or unexpected),
    }
