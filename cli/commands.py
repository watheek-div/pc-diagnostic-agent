"""Technician CLI.

All commands are read-only with respect to diagnostic data except ``service``
and ``report``/``export`` (which only write report/export artefacts).  The CLI
never starts collection on its own.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import sys
import zipfile
from datetime import datetime

from agent.config import load_config
from common import paths, time_utils
from common.system_info import collect_system_info
from diagnostics import diagnosis
from reports import report_generator
from storage.database import Database


def _open_db() -> Database:
    db = Database(paths.database_path())
    db.connect()
    return db


def _print(lines) -> None:
    for line in lines:
        print(line)


def cmd_status(args) -> int:
    db = _open_db()
    try:
        hb = db.get_heartbeat()
        latest = db.latest_session()
        incidents = db.list_incidents(limit=1)
        boot_time = latest["boot_time"] if latest else None
        _print([
            "Agent: installed",
            f"Data directory: {paths.data_dir()}",
            f"Database: {paths.database_path()}",
            f"Heartbeat: {time_utils.format_local(hb) if hb else 'never'}",
            f"Current boot: {time_utils.format_local(boot_time) if boot_time else 'n/a'}",
            f"Latest incident: {incidents[0]['incident_type'] if incidents else 'none'}",
        ])
        try:
            svc = _service_status()
            _print([f"Service: {svc}"])
        except Exception:
            _print(["Service: unknown (run as administrator for full status)"])
        return 0
    finally:
        db.close()


def cmd_info(args) -> int:
    info = collect_system_info()
    for key, value in info.items():
        print(f"{key}: {value}")
    return 0


def cmd_report(args) -> int:
    db = _open_db()
    try:
        config = load_config()
        path = report_generator.generate_report(db, config, incident_id=args.incident)
        print(f"Report written to: {path}")
        return 0
    finally:
        db.close()


def cmd_incidents(args) -> int:
    db = _open_db()
    try:
        incidents = db.list_incidents(limit=args.limit)
        if not incidents:
            print("No incidents recorded.")
            return 0
        for inc in incidents:
            print(
                f"#{inc['incident_id']} {inc['incident_type']} "
                f"confidence={inc['confidence']} at "
                f"{time_utils.format_local(inc['detected_at'])}"
            )
        return 0
    finally:
        db.close()


def cmd_events(args) -> int:
    db = _open_db()
    try:
        rows = db.query(
            "SELECT timestamp, provider, event_id, level, message FROM events "
            "ORDER BY timestamp DESC LIMIT ?",
            (args.limit,),
        )
        for r in rows:
            print(
                f"{time_utils.format_local(r['timestamp'])} | {r['provider']} | "
                f"Event {r['event_id']} | {_level_name(r['level'])}"
            )
            if args.verbose and r["message"]:
                print(f"    {(r['message'] or '')[:200]}")
        if not rows:
            print("No events recorded yet.")
        return 0
    finally:
        db.close()


def cmd_health(args) -> int:
    db = _open_db()
    try:
        ok = True
        problems = []
        try:
            db.query("SELECT 1", ())
        except Exception as exc:
            ok = False
            problems.append(f"database error: {exc}")
        hb = db.get_heartbeat()
        if hb is None:
            ok = False
            problems.append("no heartbeat recorded (agent may not be running)")
        else:
            age = time_utils.now() - hb
            if age > 180:
                ok = False
                problems.append(f"heartbeat stale by {int(age)}s")
        _print([
            f"Overall health: {'OK' if ok else 'PROBLEMS'}",
            f"Heartbeat age: {int(time_utils.now() - hb) if hb else 'n/a'}s",
        ])
        for p in problems:
            print(f"  - {p}")
        return 0 if ok else 1
    finally:
        db.close()


def cmd_diagnostics(args) -> int:
    db = _open_db()
    try:
        config = load_config()
        result = diagnosis.diagnose_latest(db, config)
        incident = result.get("incident")
        if not incident:
            print("Incident detected:\nNO")
            print("(no unexpected shutdown/reboot detected for the previous session)")
            return 0

        summary = result.get("summary") or {}
        aggregates = result.get("aggregates") or {}

        _print([
            "Incident detected:",
            "YES",
            "",
            "Type:",
            f"{incident['incident_type']}",
            "",
            "Confidence:",
            f"{incident['confidence']}",
        ])

        prev = db.get_session(incident["previous_session_id"]) if incident["previous_session_id"] else None
        _print([
            "",
            "Previous boot:",
            time_utils.format_local(prev["boot_time"]) if prev else "n/a",
            "",
            "Last healthy heartbeat:",
            time_utils.format_local(incident["last_metric_timestamp"]),
            "",
            "Current boot:",
            time_utils.format_local(incident["reboot_timestamp"]),
            "",
            "Kernel-Power 41:",
            "YES" if summary.get("kernel_power_detected") else "NO",
            "",
            "BugCheck:",
            "YES" if summary.get("bugcheck_detected") else "NO",
            "",
            "WHEA:",
            f"{summary.get('whea_count', 0)} events",
            "",
            "Disk errors:",
            str(summary.get("disk_error_count", 0)),
            "",
            "Display driver errors:",
            str(summary.get("display_error_count", 0)),
            "",
            "Maximum CPU:",
            _pct(aggregates.get("max_cpu_percent")),
            "",
            "Maximum RAM:",
            _pct(aggregates.get("max_memory_percent")),
            "",
            "Maximum temperature:",
            _temp(aggregates.get("max_temperature")),
        ])

        findings = result.get("findings") or []
        if findings:
            print("\nPrimary findings:")
            for i, f in enumerate(findings, 1):
                print(f"{i}. {f['type']} ({f['confidence']})")

        print("\nRecommended next steps:")
        steps = ["Check hardware stability", "Review WHEA events", "Check drivers", "Run hardware diagnostics"]
        for i, s in enumerate(steps, 1):
            print(f"{i}. {s}")
        return 0
    finally:
        db.close()


def cmd_simulate_incident(args) -> int:
    from simulation import runner

    config = load_config()
    try:
        result = runner.run_simulation(
            args.type,
            workspace=args.workspace,
            config=config,
            generate_report=True,
        )
    except OSError as exc:
        print(f"Simulation failed: {exc}")
        print("Tip: pass --workspace to an isolated writable directory.")
        return 1

    scenario = result["scenario"]
    incident = result.get("incident")
    summary = result.get("summary") or {}
    aggregates = result.get("aggregates") or {}
    inference = result.get("inference")
    boot_result = result.get("boot_result") or {}

    _print([
        "Scenario:",
        scenario.name,
        "",
        "Workspace:",
        os.path.dirname(os.path.dirname(result["db_path"])),
        "",
        "Simulation database:",
        result["db_path"],
    ])

    if not incident:
        _print([
            "",
            "Incident detected:",
            "NO",
            "(no unexpected shutdown/reboot detected for the previous session)",
        ])
    else:
        _print([
            "",
            "Incident detected:",
            "YES",
            "",
            "Type:",
            incident["incident_type"],
            "",
            "Confidence:",
            incident["confidence"],
            "",
            "Previous boot:",
            time_utils.format_local(scenario.prev_boot),
            "",
            "Last healthy heartbeat:",
            time_utils.format_local(incident["last_metric_timestamp"]),
            "",
            "Current boot:",
            time_utils.format_local(incident["reboot_timestamp"]),
        ])

    _print([
        "",
        "Kernel-Power 41:",
        "YES" if summary.get("kernel_power_detected") else "NO",
        "",
        "BugCheck:",
        "YES" if summary.get("bugcheck_detected") else "NO",
        "",
        "Clean shutdown event:",
        "YES" if summary.get("clean_shutdown") else "NO",
        "",
        "WHEA:",
        f"{summary.get('whea_count', 0)} events",
        "",
        "Disk errors:",
        str(summary.get("disk_error_count", 0)),
        "",
        "Display driver errors:",
        str(summary.get("display_error_count", 0)),
        "",
        "Maximum CPU:",
        _pct(aggregates.get("max_cpu_percent")),
        "",
        "Maximum RAM:",
        _pct(aggregates.get("max_memory_percent")),
    ])

    if incident:
        _print(["", "Incident evidence:"])
        for e in incident["evidence"]:
            print(f"  - {e}")

        findings = result.get("findings") or []
        if findings:
            print("\nPrimary findings:")
            for i, f in enumerate(findings, 1):
                print(f"{i}. {f['type']} ({f['confidence']})")

        print("\nRecommended next steps:")
        steps = ["Check hardware stability", "Review WHEA events", "Check drivers", "Run hardware diagnostics"]
        for i, s in enumerate(steps, 1):
            print(f"{i}. {s}")

    _print([
        "",
        "FACT",
        f"  Previous boot: {time_utils.format_local(scenario.prev_boot)}",
        f"  Current boot:  {time_utils.format_local(scenario.boot)}",
        f"  Last activity: {time_utils.format_local(scenario.last_activity)}",
        f"  Metric samples: {len(scenario.snapshots)} (every 30s, synthetic)",
        "",
        "EVIDENCE",
        f"  Kernel-Power 41 present:       {'YES' if summary.get('kernel_power_detected') else 'NO'}",
        f"  Clean shutdown event present:  {'YES' if summary.get('clean_shutdown') else 'NO'}",
        f"  Event 6008 present:            {'YES' if summary.get('unexpected_shutdown_event') else 'NO'}",
        f"  BugCheck present:              {'YES' if summary.get('bugcheck_detected') else 'NO'}",
        f"  Gap to reboot:                 "
        f"{int(inference.hang_gap_seconds) if inference and inference.hang_gap_seconds is not None else 'n/a'}s",
        "",
        "SESSION ANALYSIS",
        f"  Previous session ended cleanly:      "
        f"{'YES' if bool(boot_result.get('previous_session_clean')) else 'NO'}",
        f"  Previous session ended unexpectedly: "
        f"{'NO' if bool(boot_result.get('previous_session_clean')) else 'YES'}",
        "",
        "INFERENCE",
        f"  {_inference_summary(result)}",
        "",
        "HYPOTHESIS",
        "  This is SYNTHETIC data. It validates the classification pipeline only and",
        "  proves no real hardware, driver or power fault on any machine.",
    ])

    report_path = result.get("report_path")
    if report_path:
        _print(["", "Report written to:", report_path])
    return 0


def _inference_summary(result: dict) -> str:
    incident = result.get("incident")
    inference = result.get("inference")
    if incident is None:
        return (
            "Clean shutdown signals (6006 / User32 1074) present, no Kernel-Power 41, "
            "6008 or BugCheck -> normal restart, NO incident."
        )
    gap = inference.hang_gap_seconds if inference is not None and inference.hang_gap_seconds is not None else None
    base = (
        "not clean" if not (result.get("summary") or {}).get("clean_shutdown") else "clean"
    )
    if incident["incident_type"] == "HARD_HANG":
        gap_text = f", gap {gap:.0f}s >= 150s" if gap is not None else ""
        return f"Session {base}, Kernel-Power 41 present, no BugCheck{gap_text} -> HARD_HANG (HIGH)."
    if incident["incident_type"] == "POWER_LOSS":
        return f"Session {base}, Kernel-Power 41 present, activity stopped at reboot -> POWER_LOSS (LOW)."
    if incident["incident_type"] == "BSOD":
        return "BugCheck 1001 recorded at boot -> BSOD (HIGH)."
    return f"Classification: {incident['incident_type']} ({incident['confidence']})."


def cmd_export(args) -> int:
    db = _open_db()
    try:
        config = load_config()
        report_path = report_generator.generate_report(db, config)
        out_dir = args.output or paths.reports_dir()
        os.makedirs(out_dir, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        zip_path = os.path.join(out_dir, f"pcdiag_export_{stamp}.zip")

        files = [report_path]
        if os.path.exists(paths.database_path()):
            files.append(paths.database_path())
        if os.path.exists(paths.log_file_path()):
            files.append(paths.log_file_path())

        sysinfo_path = os.path.join(out_dir, "system_info.json")
        with open(sysinfo_path, "w", encoding="utf-8") as handle:
            json.dump(collect_system_info(), handle, indent=2)
        files.append(sysinfo_path)

        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for f in files:
                zf.write(f, arcname=os.path.basename(f))
            csv_data = _events_csv(db)
            zf.writestr("events.csv", csv_data)

        print(f"Export written to: {zip_path}")
        return 0
    finally:
        db.close()


def cmd_service(args) -> int:
    from service.windows_service import run_service_command_line

    action = args.action
    try:
        import win32serviceutil
    except ImportError:
        print("pywin32 is required to manage the service.")
        return 1

    if action in ("install", "remove", "start", "stop", "restart", "update"):
        import sys as _sys

        old_argv = _sys.argv
        if action in ("install", "update"):
            _sys.argv = ["pcdiag-service", "--startup", "auto", action]
        else:
            _sys.argv = ["pcdiag-service", action]
        try:
            win32serviceutil.HandleCommandLine(_service_class())
        finally:
            _sys.argv = old_argv
        return 0

    print(f"Unknown service action: {action}")
    return 1


def _service_class():
    from service.windows_service import AgentService

    return AgentService


def _service_status() -> str:
    import win32service
    import win32serviceutil

    return win32serviceutil.QueryServiceStatus("PCDiagnosticAgent")[1]


def _events_csv(db) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["timestamp", "provider", "event_id", "level", "message"])
    rows = db.query(
        "SELECT timestamp, provider, event_id, level, message FROM events ORDER BY timestamp"
    )
    for r in rows:
        writer.writerow([
            time_utils.format_local(r["timestamp"]),
            r["provider"],
            r["event_id"],
            _level_name(r["level"]),
            r["message"],
        ])
    return buf.getvalue()


def _level_name(level) -> str:
    return {1: "Error", 2: "Warning", 3: "Information", 4: "AuditSuccess", 5: "AuditFailure"}.get(level, str(level))


def _pct(value) -> str:
    return f"{value:.1f}%" if value is not None else "n/a"


def _temp(value) -> str:
    return f"{value:.1f}°C" if value is not None else "n/a"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pcdiag", description="PC Diagnostic Agent technician CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status", help="Show agent and data status").set_defaults(func=cmd_status)
    sub.add_parser("info", help="Show system information").set_defaults(func=cmd_info)

    p = sub.add_parser("report", help="Generate an HTML diagnostic report")
    p.add_argument("--incident", type=int, default=None, help="Report a specific incident id")
    p.set_defaults(func=cmd_report)

    p = sub.add_parser("incidents", help="List detected incidents")
    p.add_argument("--limit", type=int, default=20)
    p.set_defaults(func=cmd_incidents)

    p = sub.add_parser("events", help="Show recent Windows events")
    p.add_argument("--limit", type=int, default=50)
    p.add_argument("--verbose", action="store_true")
    p.set_defaults(func=cmd_events)

    p = sub.add_parser("health", help="Run a quick health check")
    p.set_defaults(func=cmd_health)

    sub.add_parser("diagnostics", help="Analyse the previous session").set_defaults(func=cmd_diagnostics)

    p = sub.add_parser(
        "simulate-incident",
        help="Run the diagnostic engine on isolated synthetic data (safe harness)",
    )
    p.add_argument(
        "--type",
        required=True,
        choices=["hard-hang", "power-loss", "bsod", "normal-restart"],
        help="Incident scenario to simulate",
    )
    p.add_argument(
        "--workspace",
        default=None,
        help="Isolated workspace dir (default: <data root>/test-data)",
    )
    p.set_defaults(func=cmd_simulate_incident)

    p = sub.add_parser("export", help="Export a diagnostic bundle (ZIP)")
    p.add_argument("--output", type=str, default=None)
    p.set_defaults(func=cmd_export)

    p = sub.add_parser("service", help="Manage the Windows service")
    p.add_argument("action", choices=["install", "remove", "start", "stop", "restart"])
    p.set_defaults(func=cmd_service)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
