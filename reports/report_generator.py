"""HTML diagnostic report generator.

Produces a self-contained HTML file a technician can open in any browser.  The
report distinguishes facts from hypotheses: findings carry explicit confidence
levels and evidence lists.
"""

from __future__ import annotations

import html
import json
import os
from datetime import datetime

from common import paths, system_info
from common import time_utils

_TEMPLATE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates", "report.html")

CAUSE_HINTS = {
    "POSSIBLE_HARD_HANG": ["A hard hang (system froze, no BSOD) is likely."],
    "POSSIBLE_POWER_LOSS": ["Power was likely interrupted abruptly."],
    "POSSIBLE_HARDWARE_ERROR": ["A hardware-level fault (WHEA) may be present."],
    "POSSIBLE_DRIVER_PROBLEM": ["A device driver may be misbehaving."],
    "POSSIBLE_THERMAL_PROBLEM": ["Overheating may have occurred."],
    "POSSIBLE_MEMORY_PRESSURE": ["The system may have been under memory pressure."],
    "POSSIBLE_CPU_PRESSURE": ["The system may have been under CPU load."],
    "POSSIBLE_DISK_PROBLEM": ["A storage device or driver may be failing."],
    "POSSIBLE_GPU_PROBLEM": ["The GPU or its driver may be failing."],
    "POSSIBLE_CRASH": ["A blue screen (BugCheck) was recorded."],
    "INSUFFICIENT_EVIDENCE": ["Not enough evidence to propose a cause."],
}

NEXT_STEPS = {
    "POSSIBLE_HARD_HANG": ["Review the timeline for the last activity before the freeze.",
                           "Check for driver updates (GPU, chipset, storage).",
                           "Run memory and disk diagnostics.",
                           "Inspect power delivery if it recurs."],
    "POSSIBLE_POWER_LOSS": ["Check the PSU and power connections.",
                            "Verify the machine is not on a failing UPS/surge strip.",
                            "Review Kernel-Power 41 details."],
    "POSSIBLE_HARDWARE_ERROR": ["Review WHEA events for the faulty component.",
                                "Run manufacturer hardware diagnostics.",
                                "Test RAM (memtest) and CPU under load."],
    "POSSIBLE_DRIVER_PROBLEM": ["Update the offending driver.",
                                "Check for known driver issues for the installed version."],
    "POSSIBLE_THERMAL_PROBLEM": ["Check cooling, fans, and thermal paste.",
                                 "Ensure airflow is not blocked."],
    "POSSIBLE_MEMORY_PRESSURE": ["Identify the top memory consumers.",
                                 "Consider increasing RAM or reducing workload."],
    "POSSIBLE_DISK_PROBLEM": ["Check SMART data and replace failing storage.",
                              "Check the storage driver and cable."],
    "POSSIBLE_GPU_PROBLEM": ["Reinstall/update the GPU driver.",
                             "Check GPU temperatures and seating."],
    "POSSIBLE_CRASH": ["Analyse the BugCheck code and the offending module.",
                       "Update or roll back the implicated driver."],
    "INSUFFICIENT_EVIDENCE": ["Keep the agent running and reproduce the issue.",
                              "Collect more data over a longer period."],
}


def generate_report(
    db,
    config,
    incident_id: int | None = None,
    out_path: str | None = None,
    prepend_html: str | None = None,
) -> str:
    incident = db.get_incident(incident_id) if incident_id is not None else None
    findings = db.list_findings(incident_id) if incident_id is not None else []
    if incident is None:
        latest = db.list_incidents(limit=1)
        incident = latest[0] if latest else None
        if incident is not None:
            findings = db.list_findings(incident["incident_id"])

    sections: list[str] = []
    if prepend_html:
        sections.append(prepend_html)
    sections.append(_incident_summary(incident, findings))
    sections.append(_system_info_section())
    if incident is not None:
        sections.append(_timeline_section(db, config, incident))
        sections.append(_previous_session_section(db, incident))
    sections.append(_findings_section(findings))
    sections.append(_causes_section(findings))
    sections.append(_next_steps_section(findings))

    body = "\n".join(sections)
    template = _load_template()
    rendered = template.replace("{{GENERATED_AT}}", time_utils.format_local(time_utils.now()))
    rendered = rendered.replace("{{BODY}}", body)

    out_path = out_path or os.path.join(paths.reports_dir(), "report.html")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as handle:
        handle.write(rendered)
    return out_path


def _load_template() -> str:
    try:
        with open(_TEMPLATE_PATH, "r", encoding="utf-8") as handle:
            return handle.read()
    except OSError:
        return "<html><body><h1>PC Diagnostic Report</h1><p>Generated: {{GENERATED_AT}}</p>{{BODY}}</body></html>"


def _incident_summary(incident, findings) -> str:
    if incident is None:
        return "<h2>Incident Summary</h2><div class='panel'>No incident detected. The agent is running normally.</div>"
    itype = incident["incident_type"] or "UNKNOWN"
    confidence = incident["confidence"] or "LOW"
    cls = "high" if confidence == "HIGH" else ("med" if confidence == "MEDIUM" else "low")
    rows = [
        ("Type", _esc(itype)),
        ("Confidence", f"<span class='badge {cls}'>{_esc(confidence)}</span>"),
        ("Detected at", _esc(time_utils.format_local(incident['detected_at']))),
        ("Reboot at", _esc(time_utils.format_local(incident['reboot_timestamp']))),
    ]
    if incident["last_metric_timestamp"]:
        rows.append(("Last activity", _esc(time_utils.format_local(incident['last_metric_timestamp']))))
    if incident["duration_estimate"] is not None:
        rows.append(("Estimated hang duration", f"{int(incident['duration_estimate'])} seconds"))

    table = _table(rows)
    return f"<h2>Incident Summary</h2><div class='panel'>{table}</div>"


def _system_info_section() -> str:
    info = system_info.collect_system_info()
    rows = [
        ("Hostname", _esc(str(info.get("hostname", "")))),
        ("OS", _esc(f"{info.get('platform', '')}")),
        ("CPU", _esc(str(info.get("cpu_model", "unknown")))),
        ("Logical CPUs", _esc(str(info.get("cpu_count_logical", "unknown")))),
        ("Physical CPUs", _esc(str(info.get("cpu_count_physical", "unknown")))),
        ("Total RAM", _esc(f"{info.get('total_ram_gb', 'unknown')} GB")),
    ]
    return f"<h2>System Information</h2><div class='panel'>{_table(rows)}</div>"


def _timeline_section(db, config, incident) -> str:
    start = (incident["last_metric_timestamp"] or incident["reboot_timestamp"]) - config.incident_window_before_minutes * 60
    end = (incident["reboot_timestamp"] or time_utils.now()) + config.incident_window_after_minutes * 60

    entries: list[tuple[float, str, str]] = []
    events = db.query(
        "SELECT timestamp, provider, event_id, message FROM events "
        "WHERE timestamp >= ? AND timestamp <= ? ORDER BY timestamp LIMIT 400",
        (start, end),
    )
    for ev in events:
        label = f"{ev['provider']} (Event {ev['event_id']})"
        entries.append((ev["timestamp"], label, (ev["message"] or "")[:240]))

    samples = db.query(
        "SELECT timestamp, cpu_percent FROM metrics_cpu "
        "WHERE timestamp >= ? AND timestamp <= ? ORDER BY timestamp",
        (start, end),
    )
    mem = db.query(
        "SELECT timestamp, memory_percent FROM metrics_memory "
        "WHERE timestamp >= ? AND timestamp <= ? ORDER BY timestamp",
        (start, end),
    )
    mem_map = {r["timestamp"]: r["memory_percent"] for r in mem}
    for s in samples:
        mem_pct = mem_map.get(s["timestamp"])
        if mem_pct is not None:
            detail = f"CPU {s['cpu_percent']:.0f}% · RAM {mem_pct:.0f}%"
        else:
            detail = f"CPU {s['cpu_percent']:.0f}%"
        entries.append((s["timestamp"], "Metrics", detail))

    entries.sort(key=lambda e: e[0])
    if not entries:
        return "<h2>Timeline</h2><div class='panel muted'>No data in the incident window.</div>"

    lines = []
    for ts, label, detail in entries[:300]:
        lines.append(
            f"<div class='tl'><div class='t'>{_esc(time_utils.format_clock(ts))}</div>"
            f"<div class='d'><b>{_esc(label)}</b> — {_esc(detail)}</div></div>"
        )
    return f"<h2>Timeline</h2><div class='panel timeline'>{''.join(lines)}</div>"


def _previous_session_section(db, incident) -> str:
    session_id = incident["previous_session_id"]
    if not session_id:
        return "<h2>Previous Session</h2><div class='panel muted'>No prior session recorded by this agent.</div>"
    session = db.get_session(session_id)
    if session is None:
        return "<h2>Previous Session</h2><div class='panel muted'>Previous session data unavailable.</div>"
    clean = "Yes" if session["previous_session_clean"] == 1 else ("No" if session["previous_session_clean"] == 0 else "Unknown")
    unexpected = "No" if session["previous_session_clean"] == 1 else ("Yes" if session["previous_session_clean"] == 0 else "Unknown")
    rows = [
        ("Previous boot", _esc(time_utils.format_local(session["boot_time"]))),
        ("Previous session ended cleanly", _esc(clean)),
        ("Previous session ended unexpectedly", _esc(unexpected)),
        ("Kernel-Power 41", "Yes" if session["kernel_power_detected"] else "No"),
        ("BugCheck", "Yes" if session["bugcheck_detected"] else "No"),
        ("Uptime before boot", _fmt_duration(session["uptime_before_boot"])),
    ]
    return f"<h2>Previous Session</h2><div class='panel'>{_table(rows)}</div>"


def _findings_section(findings) -> str:
    if not findings:
        return "<h2>Findings</h2><div class='panel muted'>No findings.</div>"
    blocks = []
    for f in findings:
        cls = "high" if f["severity"] == "HIGH" else ("med" if f["severity"] == "MEDIUM" else "low")
        evidence = json.loads(f["evidence"]) if isinstance(f["evidence"], str) else (f["evidence"] or [])
        ev_html = "".join(f"<li>{_esc(str(e))}</li>" for e in evidence)
        blocks.append(
            f"<div class='finding'><b>{_esc(f['finding_type'])}</b> "
            f"<span class='badge {cls}'>{_esc(f['severity'] or '')}</span> "
            f"<span class='muted'>confidence {_esc(f['confidence'] or '')}</span>"
            f"<div class='muted'>{_esc(f['explanation'] or '')}</div>"
            f"<ul>{ev_html}</ul></div>"
        )
    return f"<h2>Findings</h2>{''.join(blocks)}"


def _causes_section(findings) -> str:
    causes = []
    for f in findings:
        hints = CAUSE_HINTS.get(f["finding_type"])
        if hints:
            causes.extend(hints)
    causes = list(dict.fromkeys(causes))
    if not causes:
        causes = ["No probable cause could be determined."]
    items = "".join(f"<li>{_esc(c)}</li>" for c in causes)
    return f"<h2>Possible Causes</h2><div class='panel'><ul>{items}</ul></div>"


def _next_steps_section(findings) -> str:
    steps = []
    for f in findings:
        steps.extend(NEXT_STEPS.get(f["finding_type"], []))
    steps = list(dict.fromkeys(steps))
    if not steps:
        steps = ["Continue monitoring with the agent installed."]
    items = "".join(f"<li>{_esc(s)}</li>" for s in steps)
    return f"<h2>Recommended Next Steps</h2><div class='panel'><ul>{items}</ul></div>"


def _table(rows) -> str:
    body = "".join(f"<tr><th>{_esc(str(k))}</th><td>{v}</td></tr>" for k, v in rows)
    return f"<table>{body}</table>"


def _fmt_duration(seconds: float | None) -> str:
    if seconds is None:
        return "n/a"
    seconds = int(seconds)
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{hours}h {minutes}m {secs}s"


def _esc(value) -> str:
    return html.escape(str(value))
