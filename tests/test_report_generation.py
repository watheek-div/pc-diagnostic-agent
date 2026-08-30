"""Report generation tests."""

import os

from reports.report_generator import generate_report


def test_generate_report_for_incident(db, config, tmp_path):
    db.create_session(1000.0, 1000.0)
    db.insert_events(
        [{"timestamp": 1900.0, "provider": "Microsoft-Windows-Kernel-Power", "event_id": 41, "level": 1, "message": "reboot"}],
        session_id=1,
    )
    incident_id = db.create_incident(
        {
            "detected_at": 2000.0, "incident_type": "HARD_HANG", "confidence": "HIGH",
            "previous_session_id": 1, "last_metric_timestamp": 1700.0,
            "reboot_timestamp": 2000.0, "duration_estimate": 300.0,
            "findings": ["POSSIBLE_HARD_HANG"], "evidence": ["no clean shutdown"],
        },
        [{
            "type": "POSSIBLE_HARD_HANG", "severity": "HIGH", "confidence": "HIGH",
            "evidence": ["no clean shutdown"], "timestamp": 2000.0,
            "explanation": "System froze and was force-restarted.",
        }],
    )
    out = str(tmp_path / "report.html")
    path = generate_report(db, config, incident_id=incident_id, out_path=out)
    assert path == out
    assert os.path.exists(out)
    content = open(out, encoding="utf-8").read()
    assert "PC Diagnostic Report" in content
    assert "HARD_HANG" in content
    assert "Incident Summary" in content


def test_generate_report_no_incident(db, config, tmp_path):
    out = str(tmp_path / "report.html")
    generate_report(db, config, incident_id=None, out_path=out)
    assert os.path.exists(out)
    content = open(out, encoding="utf-8").read()
    assert "PC Diagnostic Report" in content
