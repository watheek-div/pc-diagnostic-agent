"""Windows event categorization.

Maps raw event rows onto coarse diagnostic categories so the analysis engine
can treat "disk", "display/driver", "WHEA/hardware", "kernel-power", etc. as
evidence without depending on exact provider strings everywhere.
"""

from __future__ import annotations

KERNEL_POWER_PROVIDERS = {"Microsoft-Windows-Kernel-Power", "Kernel-Power"}
BUGCHECK_PROVIDERS = {
    "Microsoft-Windows-WER-SystemErrorReporting",
    "BugCheck",
    "Microsoft-Windows-WER-SystemErrorReporting ",
}
WHEA_PROVIDERS = {"Microsoft-Windows-WHEA-Logger", "WHEA-Logger"}
DISK_PROVIDERS = {"disk", "ntfs", "storahci", "stornvme", "iaStor", "msahci"}
DISPLAY_PROVIDERS = {
    "display", "dxgkrnl", "nvlddmkm", "amdkmdag", "igfx", "igdkmd64",
    "igfxCUIService", "aticfx64",
}
EVENTLOG_PROVIDER = "EventLog"

DISK_ERROR_EVENT_IDS = {7, 9, 11, 15, 51, 52, 55, 98, 129, 140, 153, 157}
SHUTDOWN_CLEAN_IDS = {6006, 1074}
SHUTDOWN_UNEXPECTED_IDS = {6008}


def _provider(ev: dict) -> str:
    return (ev.get("provider") or "").strip()


def _contains_any(text: str, needles: set[str]) -> bool:
    low = text.lower()
    return any(needle.lower() in low for needle in needles)


def event_id(ev: dict) -> int | None:
    """Normalised event identifier.

    The classic Event Log API surfaces some IDs with the high bit set (stored
    as signed negative integers).  The low 16 bits always hold the true event
    ID, so we mask to compare consistently regardless of storage format.
    """
    raw = ev.get("event_id")
    if raw is None:
        return None
    try:
        return int(raw) & 0xFFFF
    except (TypeError, ValueError):
        return None


def classify_event(ev: dict) -> str | None:
    provider = _provider(ev)
    event_id_value = event_id(ev)
    message = (ev.get("message") or "").lower()

    if event_id_value == 41 and (
        _contains_any(provider, KERNEL_POWER_PROVIDERS)
        or provider == EVENTLOG_PROVIDER
    ):
        return "kernel_power"

    if _contains_any(provider, BUGCHECK_PROVIDERS) or (
        event_id_value == 1001 and "bugcheck" in message
    ):
        return "bugcheck"

    if _contains_any(provider, WHEA_PROVIDERS) or "whea" in provider.lower():
        return "whea"

    if (
        _contains_any(provider, DISK_PROVIDERS)
        and event_id_value in DISK_ERROR_EVENT_IDS
    ):
        return "disk"

    if _contains_any(provider, DISPLAY_PROVIDERS):
        return "display"

    if event_id_value in SHUTDOWN_CLEAN_IDS:
        return "shutdown_clean"

    if event_id_value in SHUTDOWN_UNEXPECTED_IDS:
        return "shutdown_unexpected"

    if provider == "Service Control Manager":
        return "service_control"

    return "other"


def summarize(events: list[dict]) -> dict:
    """Return category counts plus lists of high-interest evidence events."""
    counts: dict[str, int] = {}
    by_category: dict[str, list[dict]] = {}
    for ev in events:
        cat = classify_event(ev) or "other"
        counts[cat] = counts.get(cat, 0) + 1
        by_category.setdefault(cat, []).append(ev)

    return {
        "counts": counts,
        "kernel_power_count": counts.get("kernel_power", 0),
        "bugcheck_count": counts.get("bugcheck", 0),
        "whea_count": counts.get("whea", 0),
        "disk_error_count": counts.get("disk", 0),
        "display_error_count": counts.get("display", 0),
        "clean_shutdown": counts.get("shutdown_clean", 0) > 0,
        "unexpected_shutdown_event": counts.get("shutdown_unexpected", 0) > 0,
        "kernel_power_detected": counts.get("kernel_power", 0) > 0,
        "bugcheck_detected": counts.get("bugcheck", 0) > 0,
        "whea_events": by_category.get("whea", []),
        "disk_events": by_category.get("disk", []),
        "display_events": by_category.get("display", []),
        "kernel_power_events": by_category.get("kernel_power", []),
        "bugcheck_events": by_category.get("bugcheck", []),
    }
