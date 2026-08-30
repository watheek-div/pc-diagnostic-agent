"""Rule-based diagnostic engine (V1 — no LLM).

Correlates metrics, events, boot history, temperatures, disk/memory/CPU
pressure and crash signals into a ranked list of findings with
severity/confidence/evidence.  Findings are hypotheses, never certainties.
"""

from __future__ import annotations

import logging

from diagnostics import event_analyzer
from diagnostics.crash_detector import detect_crash
from diagnostics.hang_detector import infer_termination

logger = logging.getLogger(__name__)

SEVERITY_LOW = "LOW"
SEVERITY_MEDIUM = "MEDIUM"
SEVERITY_HIGH = "HIGH"

INCIDENT_HARD_HANG = "HARD_HANG"
INCIDENT_BSOD = "BSOD"
INCIDENT_UNEXPECTED_REBOOT = "UNEXPECTED_REBOOT"
INCIDENT_POWER_LOSS = "POWER_LOSS"
INCIDENT_UNKNOWN = "UNKNOWN"

FINDING_HARD_HANG = "POSSIBLE_HARD_HANG"
FINDING_POWER_LOSS = "POSSIBLE_POWER_LOSS"
FINDING_HARDWARE = "POSSIBLE_HARDWARE_ERROR"
FINDING_DRIVER = "POSSIBLE_DRIVER_PROBLEM"
FINDING_THERMAL = "POSSIBLE_THERMAL_PROBLEM"
FINDING_MEMORY = "POSSIBLE_MEMORY_PRESSURE"
FINDING_CPU = "POSSIBLE_CPU_PRESSURE"
FINDING_DISK = "POSSIBLE_DISK_PROBLEM"
FINDING_GPU = "POSSIBLE_GPU_PROBLEM"
FINDING_INSUFFICIENT = "INSUFFICIENT_EVIDENCE"


def run_diagnosis(db, boot_result: dict, config, persist: bool = True) -> dict:
    boot_time = boot_result["boot_time"]
    prev_boot = boot_result["previous_boot_time"]

    transition_start = prev_boot if prev_boot is not None else boot_time - config.retention_hours * 3600.0
    transition_end = boot_time + 120.0
    transition_events = _events_between(db, transition_start, transition_end)
    transition_summary = event_analyzer.summarize(transition_events)

    incident_start = boot_time - config.incident_window_before_minutes * 60.0
    incident_end = boot_time + config.incident_window_after_minutes * 60.0
    incident_events = _events_between(db, incident_start, incident_end)
    incident_summary = event_analyzer.summarize(incident_events)

    crash = detect_crash(transition_summary, boot_result["previous_session_clean"])
    last_activity = _last_metric_timestamp(db, before=boot_time)
    aggregates = _aggregates(db, incident_start, incident_end)

    inference = infer_termination(
        crash, last_activity, boot_time, config.collection_interval_seconds
    )

    findings = _build_findings(incident_summary, aggregates, inference, config)

    warranted = crash["unexpected_shutdown"] or crash["bugcheck_detected"]
    if not warranted:
        return {"incident": None, "findings": [], "summary": incident_summary, "aggregates": aggregates}

    incident_type = _incident_type(inference, crash)
    confidence = _incident_confidence(inference, crash, findings)

    incident = {
        "detected_at": boot_time,
        "incident_type": incident_type,
        "confidence": confidence,
        "previous_session_id": boot_result["previous_session_id"],
        "last_metric_timestamp": last_activity,
        "reboot_timestamp": boot_time,
        "duration_estimate": inference.hang_gap_seconds,
        "findings": [f["type"] for f in findings],
        "evidence": _evidence(incident_summary, aggregates, inference, crash),
    }
    if persist and not _incident_exists(db, boot_result["previous_session_id"], boot_time):
        incident_id = db.create_incident(incident, findings)
        incident["incident_id"] = incident_id

    return {
        "incident": incident,
        "findings": findings,
        "summary": incident_summary,
        "aggregates": aggregates,
        "inference": inference,
    }


def _incident_exists(db, previous_session_id, reboot_timestamp) -> bool:
    rows = db.query(
        "SELECT incident_id FROM incidents WHERE reboot_timestamp >= ? AND reboot_timestamp <= ?",
        (reboot_timestamp - 5.0, reboot_timestamp + 5.0),
    )
    return len(rows) > 0


def _build_findings(summary, aggregates, inference, config) -> list[dict]:
    findings: list[dict] = []

    if summary["whea_count"] > 0:
        severity = SEVERITY_HIGH if summary["whea_count"] >= 3 else SEVERITY_MEDIUM
        confidence = "HIGH" if summary["whea_count"] >= 3 else "MEDIUM"
        findings.append(
            {
                "type": FINDING_HARDWARE,
                "severity": severity,
                "confidence": confidence,
                "evidence": [
                    f"{summary['whea_count']} WHEA hardware error event(s) detected"
                ],
                "timestamp": _first_ts(summary["whea_events"]),
                "explanation": (
                    "Windows Hardware Error Architecture (WHEA) events occurred "
                    "around the incident window. This points to a hardware-level "
                    "fault and warrants hardware diagnostics."
                ),
            }
        )

    if summary["disk_error_count"] > 0:
        findings.append(
            {
                "type": FINDING_DISK,
                "severity": SEVERITY_MEDIUM,
                "confidence": "MEDIUM",
                "evidence": [
                    f"{summary['disk_error_count']} disk/storage error event(s) detected"
                ],
                "timestamp": _first_ts(summary["disk_events"]),
                "explanation": (
                    "Disk or filesystem/storage driver error events were logged. "
                    "Storage problems can cause freezes."
                ),
            }
        )

    if summary["display_error_count"] > 0:
        findings.append(
            {
                "type": FINDING_GPU,
                "severity": SEVERITY_MEDIUM,
                "confidence": "MEDIUM",
                "evidence": [
                    f"{summary['display_error_count']} display/graphics driver error event(s)"
                ],
                "timestamp": _first_ts(summary["display_events"]),
                "explanation": (
                    "Display driver errors were logged. A failing or buggy GPU "
                    "driver can cause hard hangs."
                ),
            }
        )

    max_temp = aggregates.get("max_temperature")
    if max_temp is not None and max_temp >= config.temperature_critical_celsius:
        findings.append(
            {
                "type": FINDING_THERMAL,
                "severity": SEVERITY_HIGH,
                "confidence": "MEDIUM",
                "evidence": [f"Maximum temperature reached {max_temp:.1f}°C"],
                "timestamp": None,
                "explanation": (
                    "A critical temperature threshold was exceeded. Overheating "
                    "can trigger sudden shutdowns or throttling-induced hangs."
                ),
            }
        )

    max_mem = aggregates.get("max_memory_percent")
    if max_mem is not None and max_mem >= config.memory_warning_percent:
        findings.append(
            {
                "type": FINDING_MEMORY,
                "severity": SEVERITY_MEDIUM,
                "confidence": "LOW",
                "evidence": [f"Memory usage peaked at {max_mem:.1f}%"],
                "timestamp": None,
                "explanation": (
                    "Sustained high memory pressure was observed. This is "
                    "evidence, not proof of a defect."
                ),
            }
        )

    max_cpu = aggregates.get("max_cpu_percent")
    if max_cpu is not None and max_cpu >= config.cpu_warning_percent:
        findings.append(
            {
                "type": FINDING_CPU,
                "severity": SEVERITY_LOW,
                "confidence": "LOW",
                "evidence": [f"CPU utilisation peaked at {max_cpu:.1f}%"],
                "timestamp": None,
                "explanation": "High CPU utilisation was observed before the incident.",
            }
        )

    if inference.probable_hard_hang:
        findings.append(
            {
                "type": FINDING_HARD_HANG,
                "severity": SEVERITY_HIGH,
                "confidence": inference.confidence,
                "evidence": _hang_evidence(inference),
                "timestamp": None,
                "explanation": (
                    "The system stopped writing diagnostics before an unclean "
                    "reboot with no BugCheck. This is consistent with a hard hang "
                    "followed by a forced restart."
                ),
            }
        )
    elif inference.probable_power_loss:
        findings.append(
            {
                "type": FINDING_POWER_LOSS,
                "severity": SEVERITY_HIGH,
                "confidence": inference.confidence,
                "evidence": ["Kernel-Power 41 present", "No clean shutdown"],
                "timestamp": None,
                "explanation": (
                    "Abrupt power interruption is possible. Kernel-Power 41 alone "
                    "does not prove a PSU failure."
                ),
            }
        )
    elif inference.probable_crash:
        findings.append(
            {
                "type": "POSSIBLE_CRASH",
                "severity": SEVERITY_HIGH,
                "confidence": "HIGH",
                "evidence": ["BugCheck event detected"],
                "timestamp": None,
                "explanation": "A BugCheck (blue screen) was recorded.",
            }
        )

    if not findings:
        findings.append(
            {
                "type": FINDING_INSUFFICIENT,
                "severity": SEVERITY_LOW,
                "confidence": "LOW",
                "evidence": [],
                "timestamp": None,
                "explanation": "Not enough evidence to propose a cause.",
            }
        )

    findings.sort(key=lambda f: _severity_rank(f["severity"]), reverse=True)
    return findings


def _hang_evidence(inference) -> list[str]:
    ev = ["No clean shutdown event", "Unclean reboot detected", "No BugCheck"]
    if inference.hang_gap_seconds is not None:
        ev.append(
            f"Diagnostics stopped {inference.hang_gap_seconds:.0f}s before reboot"
        )
    return ev


def _evidence(summary, aggregates, inference, crash) -> list[str]:
    ev: list[str] = []
    if crash["kernel_power_detected"]:
        ev.append("Kernel-Power 41 detected")
    if crash["bugcheck_detected"]:
        ev.append("BugCheck detected")
    if summary["whea_count"]:
        ev.append(f"{summary['whea_count']} WHEA event(s)")
    if summary["disk_error_count"]:
        ev.append(f"{summary['disk_error_count']} disk error event(s)")
    if summary["display_error_count"]:
        ev.append(f"{summary['display_error_count']} display error event(s)")
    if not crash["clean_shutdown"]:
        ev.append("No clean shutdown event")
    if inference.hang_gap_seconds is not None:
        ev.append(
            f"Diagnostics stopped {inference.hang_gap_seconds:.0f}s before reboot"
        )
    if aggregates.get("max_temperature") is not None:
        ev.append(f"Max temperature {aggregates['max_temperature']:.1f}°C")
    if aggregates.get("max_memory_percent") is not None:
        ev.append(f"Max RAM {aggregates['max_memory_percent']:.1f}%")
    if aggregates.get("max_cpu_percent") is not None:
        ev.append(f"Max CPU {aggregates['max_cpu_percent']:.1f}%")
    return ev


def _incident_type(inference, crash) -> str:
    if crash["bugcheck_detected"]:
        return INCIDENT_BSOD
    if inference.probable_hard_hang:
        return INCIDENT_HARD_HANG
    if inference.probable_power_loss:
        return INCIDENT_POWER_LOSS
    if crash["unexpected_shutdown"]:
        return INCIDENT_UNEXPECTED_REBOOT
    return INCIDENT_UNKNOWN


def _incident_confidence(inference, crash, findings) -> str:
    if crash["bugcheck_detected"]:
        return "HIGH"
    if inference.probable_hard_hang or inference.probable_power_loss:
        return inference.confidence
    ranks = {"HIGH": 3, "MEDIUM": 2, "LOW": 1}
    best = "LOW"
    for f in findings:
        if ranks.get(f.get("confidence"), 1) > ranks[best]:
            best = f.get("confidence", "LOW")
    return best


def _severity_rank(sev: str) -> int:
    return {"HIGH": 3, "MEDIUM": 2, "LOW": 1}.get(sev, 0)


def _first_ts(events: list[dict]) -> float | None:
    if not events:
        return None
    return min((e.get("timestamp") for e in events if e.get("timestamp")), default=None)


def _events_between(db, start: float, end: float) -> list[dict]:
    rows = db.query(
        "SELECT * FROM events WHERE timestamp >= ? AND timestamp <= ? ORDER BY timestamp",
        (start, end),
    )
    return [dict(r) for r in rows]


def _last_metric_timestamp(db, before: float) -> float | None:
    tables = ["metrics_cpu", "metrics_memory", "metrics_uptime", "metrics_process"]
    max_ts: float | None = None
    for table in tables:
        rows = db.query(
            f"SELECT MAX(timestamp) AS m FROM {table} WHERE timestamp < ?", (before,)
        )
        if rows and rows[0]["m"] is not None:
            max_ts = rows[0]["m"] if max_ts is None else max(max_ts, rows[0]["m"])
    hb = db.get_heartbeat()
    if hb is not None and hb < before:
        max_ts = hb if max_ts is None else max(max_ts, hb)
    return max_ts


def _aggregates(db, start: float, end: float) -> dict:
    def max_of(table: str, column: str) -> float | None:
        rows = db.query(
            f"SELECT MAX({column}) AS m FROM {table} "
            "WHERE timestamp >= ? AND timestamp <= ?",
            (start, end),
        )
        return rows[0]["m"] if rows and rows[0]["m"] is not None else None

    return {
        "max_cpu_percent": max_of("metrics_cpu", "cpu_percent"),
        "max_memory_percent": max_of("metrics_memory", "memory_percent"),
        "max_temperature": max_of("metrics_temperature", "temperature_c"),
        "max_disk_percent": max_of("metrics_disk", "percent"),
    }


def diagnose_latest(db, config) -> dict:
    """Run the diagnostic engine against the latest session without persisting.

    Used by the on-demand CLI ``diagnostics`` command.  Reconstructs the boot
    result from the latest two session rows.
    """
    latest = db.latest_session()
    if latest is None:
        return {"incident": None, "findings": [], "summary": None, "aggregates": {}}

    prev_rows = db.query(
        "SELECT * FROM sessions WHERE session_id < ? ORDER BY session_id DESC LIMIT 1",
        (latest["session_id"],),
    )
    prev = prev_rows[0] if prev_rows else None

    def _as_bool(v):
        return None if v is None else bool(v)

    boot_result = {
        "boot_time": latest["boot_time"],
        "previous_boot_time": latest["previous_boot_time"] or (prev["boot_time"] if prev else None),
        "previous_session_id": prev["session_id"] if prev else None,
        "previous_session_clean": _as_bool(prev["previous_session_clean"]) if prev else None,
    }
    return run_diagnosis(db, boot_result, config, persist=False)
