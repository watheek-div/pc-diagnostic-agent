"""Hard-hang inference.

A true hard hang cannot be self-observed by the frozen machine.  This module
therefore infers the *probable* termination mode from post-reboot evidence
using confidence levels (LOW/MEDIUM/HIGH) — never certainty.
"""

from __future__ import annotations

from dataclasses import dataclass

LOW = "LOW"
MEDIUM = "MEDIUM"
HIGH = "HIGH"


@dataclass
class TerminationInference:
    probable_normal_shutdown: bool = False
    probable_crash: bool = False
    probable_hard_hang: bool = False
    probable_power_loss: bool = False
    confidence: str = LOW
    hang_gap_seconds: float | None = None


def infer_termination(
    crash: dict,
    last_activity_timestamp: float | None,
    reboot_timestamp: float,
    collection_interval: int,
) -> TerminationInference:
    """Infer the most likely termination mode of the previous session.

    ``last_activity_timestamp`` is the latest metric/heartbeat timestamp from
    the previous session (None if the agent collected nothing).
    """
    result = TerminationInference()

    if crash.get("clean_shutdown"):
        result.probable_normal_shutdown = True
        result.confidence = HIGH
        return result

    if crash.get("bugcheck_detected"):
        result.probable_crash = True
        result.confidence = HIGH
        return result

    if not crash.get("unexpected_shutdown"):
        # No clean shutdown, no bugcheck, no kernel-power -> not enough evidence.
        return result

    gap = None
    if last_activity_timestamp is not None:
        gap = max(0.0, reboot_timestamp - last_activity_timestamp)
        result.hang_gap_seconds = gap

    if crash.get("kernel_power_detected"):
        if gap is None:
            # Metrics never got collected in the previous session: we know the
            # reboot was unexpected but cannot estimate the freeze duration.
            result.probable_hard_hang = True
            result.confidence = LOW
        elif gap >= collection_interval * 5:
            result.probable_hard_hang = True
            result.confidence = HIGH
        elif gap >= collection_interval * 2:
            result.probable_hard_hang = True
            result.confidence = MEDIUM
        else:
            # Activity stopped essentially at reboot time: consistent with an
            # abrupt power loss rather than a prolonged freeze.
            result.probable_power_loss = True
            result.confidence = LOW
    else:
        # 6008 without Kernel-Power 41 is still an unexpected shutdown.
        result.probable_hard_hang = True
        result.confidence = LOW

    return result
