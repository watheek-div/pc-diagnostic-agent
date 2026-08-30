"""Run the real diagnostic engine against isolated synthetic data.

The harness creates a throwaway SQLite database under the simulation workspace
(default: ``<data root>/test-data``), seeds it with a fully deterministic
previous session, then drives the same ``detect_boot`` / ``run_diagnosis`` code
path used in production.  The live production database is never opened or
written; no Windows event log is read; nothing on the OS is stressed or forced.
"""

from __future__ import annotations

import html
import os

from agent.config import Config, load_config
from common import paths, time_utils
from diagnostics.boot_detector import detect_boot
from diagnostics.diagnosis import run_diagnosis
from reports import report_generator
from simulation.scenarios import Scenario, get_scenario
from storage.database import Database

DB_FILENAME = "simulation.db"


def default_workspace() -> str:
    return paths.test_data_dir()


def run_simulation(
    scenario_type: str,
    workspace: str | None = None,
    config: Config | None = None,
    generate_report: bool = True,
) -> dict:
    """Seed an isolated DB and run the real engine.

    Returns a dict with ``incident`` (or None), ``findings``, ``summary``,
    ``aggregates``, ``boot_result``, ``scenario``, ``db_path`` and (when
    ``generate_report``) ``report_path``.
    """
    scenario = get_scenario(scenario_type)
    if config is None:
        config = load_config()

    workspace = workspace or default_workspace()
    workspace = os.path.abspath(workspace)
    scenario_dir = os.path.join(workspace, "scenarios")
    db_path = os.path.join(scenario_dir, DB_FILENAME)
    os.makedirs(scenario_dir, exist_ok=True)

    # Fresh, deterministic database for every run.
    for suffix in ("", "-wal", "-shm", "-journal"):
        candidate = db_path + suffix
        if os.path.exists(candidate):
            os.remove(candidate)

    db = Database(db_path)
    db.connect()
    try:
        _seed(db, scenario)
        boot_result = detect_boot(db, now=scenario.boot, boot_time=scenario.boot)
        result = run_diagnosis(db, boot_result, config, persist=True)
        result["scenario"] = scenario
        result["db_path"] = db_path
        result["boot_result"] = boot_result
        if generate_report:
            report_path = _write_report(db, config, result, workspace)
            result["report_path"] = report_path
        return result
    finally:
        db.close()


def _seed(db: Database, scenario: Scenario) -> None:
    prev_id = db.create_session(scenario.prev_boot, scenario.prev_boot)
    db.insert_events(scenario.events, session_id=prev_id)
    for ts, snapshot in scenario.snapshots:
        db.insert_snapshot(snapshot, ts, prev_id)
    for hb in scenario.heartbeats:
        db.update_heartbeat(hb)


def _write_report(db: Database, config: Config, result: dict, workspace: str) -> str:
    prepend = _annotation_html(db, config, result)
    out_path = os.path.join(workspace, f"report-{result['scenario'].name}.html")
    return report_generator.generate_report(
        db, config, out_path=out_path, prepend_html=prepend
    )


def _annotation_html(db: Database, config: Config, result: dict) -> str:
    scenario: Scenario = result["scenario"]
    incident = result.get("incident")
    summary = result.get("summary") or {}
    aggregates = result.get("aggregates") or {}
    boot = scenario.boot
    prev = scenario.prev_boot

    incident_start = boot - config.incident_window_before_minutes * 60.0
    incident_end = boot + config.incident_window_after_minutes * 60.0
    disk_rows = db.query(
        "SELECT MAX(percent) AS m FROM metrics_disk WHERE timestamp >= ? AND timestamp <= ?",
        (incident_start, incident_end),
    )
    max_disk = disk_rows[0]["m"] if disk_rows else None

    fact_rows = [
        ("Scenario", _esc(scenario.name)),
        ("Previous boot", _esc(time_utils.format_local(prev))),
        ("Current boot", _esc(time_utils.format_local(boot))),
        ("Last activity (metrics/heartbeat)", _esc(time_utils.format_local(scenario.last_activity))),
        ("Metric samples", _esc(str(len(scenario.snapshots)))),
        ("Maximum CPU", _esc(_pct(aggregates.get("max_cpu_percent")))),
        ("Maximum RAM", _esc(_pct(aggregates.get("max_memory_percent")))),
        ("Maximum disk utilisation", _esc(_pct(max_disk))),
    ]
    evidence_rows = [
        ("Kernel-Power 41 present", _esc("YES" if summary.get("kernel_power_detected") else "NO")),
        ("Clean shutdown event present", _esc("YES" if summary.get("clean_shutdown") else "NO")),
        ("Event 6008 present", _esc("YES" if summary.get("unexpected_shutdown_event") else "NO")),
        ("BugCheck present", _esc("YES" if summary.get("bugcheck_detected") else "NO")),
        ("Disk/storage error events",
         _esc(str(summary.get("disk_error_count", 0)))),
        ("Display driver error events",
         _esc(str(summary.get("display_error_count", 0)))),
    ]
    if incident:
        evidence_rows.extend([
            ("Estimated hang duration",
             _esc(f"{int(incident['duration_estimate'])} seconds") if incident["duration_estimate"] is not None else _esc("n/a")),
            ("Incident confidence", _esc(incident["confidence"])),
        ])

    # Session-level state. "Ended unexpectedly" is the direct complement of
    # "ended cleanly" so the two rows can never read as contradictory facts.
    boot_result = result.get("boot_result") or {}
    prev_clean = boot_result.get("previous_session_clean")
    session_rows = [
        ("Previous session ended cleanly", _esc(_cleanly(prev_clean))),
        ("Previous session ended unexpectedly", _esc(_unexpectedly(prev_clean))),
    ]

    inference = _inference_text(result)

    blocks = [
        "<div class='panel' style='border-left:3px solid var(--crit);'>"
        "<b>SIMULATION / TEST DATA — NOT PRODUCTION</b><br>"
        "<span class='muted'>This report was generated from fully synthetic data by the "
        "<code>simulate-incident</code> harness. It exercises the diagnostic pipeline only "
        "and contains no evidence about any real machine.</span></div>",
        "<h2>FACT</h2><div class='panel'>" + _table(fact_rows) + "</div>",
        "<h2>EVIDENCE</h2><div class='panel'>" + _table(evidence_rows) + "</div>",
        "<h2>SESSION ANALYSIS</h2><div class='panel'>" + _table(session_rows) + "</div>",
        "<h2>INFERENCE</h2><div class='panel'><p>" + inference + "</p></div>",
        "<h2>HYPOTHESIS</h2><div class='panel'><p>"
        "The classification above is a hypothesis inferred from synthetic events. "
        "It does NOT prove a real hardware, driver or power fault on any machine. "
        "In production, act only on live logs and repeatable reproductions.</p></div>",
    ]
    return "\n".join(blocks)


def _inference_text(result: dict) -> str:
    scenario: Scenario = result["scenario"]
    incident = result.get("incident")
    summary = result.get("summary") or {}
    inference = result.get("inference")

    if incident is None:
        return (
            "The previous session ended with a clean shutdown signal "
            "(EventLog 6006 / User32 1074 in the boot window). No Kernel-Power 41, "
            "event 6008 or BugCheck was detected, so the engine correctly created "
            "NO incident for this normal restart."
        )

    bits = [
        f"previous clean shutdown = {'YES' if summary.get('clean_shutdown') else 'NO'}",
        f"Kernel-Power 41 = {'YES' if summary.get('kernel_power_detected') else 'NO'}",
        f"BugCheck = {'YES' if summary.get('bugcheck_detected') else 'NO'}",
    ]
    if inference is not None and inference.hang_gap_seconds is not None:
        bits.append(
            f"diagnostics stopped {inference.hang_gap_seconds:.0f}s before reboot"
        )
    if incident["incident_type"] == "HARD_HANG":
        gap = inference.hang_gap_seconds if inference is not None else None
        gap_text = f" (gap {gap:.0f}s)" if gap is not None else ""
        return (
            " and ".join(bits) + f". The diagnostic gap{gap_text} meets the hard-hang "
            "threshold (>= 5 x collection interval = 150s), the previous session was "
            "NOT clean, there is no BugCheck, and Kernel-Power 41 is present. The "
            "engine infers a probable hard hang at HIGH confidence."
        )
    if incident["incident_type"] == "POWER_LOSS":
        return (
            " and ".join(bits) + ". The gap is under 2 x the collection interval "
            "(<= 60s), so activity stopped essentially at reboot time with no clean "
            "shutdown and no BugCheck. The engine infers an abrupt power loss at "
            "LOW confidence (Kernel-Power 41 alone is not proof of a PSU fault)."
        )
    if incident["incident_type"] == "BSOD":
        return (
            " and ".join(bits) + ". A BugCheck 1001 event was recorded at boot; "
            "that is direct crash evidence, so the engine classifies the transition "
            "as BSOD at HIGH confidence."
        )
    return " and ".join(bits) + ". No strong inference applicable; inspect the incident report."


def _table(rows: list[tuple[str, str]]) -> str:
    body = "".join(f"<tr><th>{k}</th><td>{v}</td></tr>" for k, v in rows)
    return f"<table>{body}</table>"


def _esc(value) -> str:
    return html.escape(str(value))


def _pct(value) -> str:
    return f"{value:.1f}%" if value is not None else "n/a"


def _cleanly(value) -> str:
    if value is None:
        return "UNKNOWN"
    return "YES" if value else "NO"


def _unexpectedly(value) -> str:
    if value is None:
        return "UNKNOWN"
    return "NO" if value else "YES"


def expected_outcome(scenario_type: str) -> tuple[str | None, str | None]:
    """Return the (expected_incident_type, expected_confidence) for a scenario."""
    scenario = get_scenario(scenario_type)
    return scenario.expected_type, scenario.expected_confidence