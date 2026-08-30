"""Retention tests."""

import time

from storage import retention


def _insert_metrics(db, table, timestamps, session_id=1):
    for ts in timestamps:
        if table == "metrics_cpu":
            db.insert_snapshot({"metrics_cpu": [{"cpu_percent": 1.0, "cpu_frequency": None, "processor_count": 1}]}, ts, session_id)
        elif table == "metrics_memory":
            db.insert_snapshot({"metrics_memory": [{"memory_percent": 1.0}]}, ts, session_id)


def test_prune_removes_old_metrics(db):
    now = time.time()
    old = now - 50 * 3600
    recent = now - 60
    _insert_metrics(db, "metrics_cpu", [old, recent])
    result = retention.prune_metrics(db, retention_hours=24)
    assert result["deleted_rows"] == 1
    rows = db.query("SELECT timestamp FROM metrics_cpu")
    assert len(rows) == 1
    assert abs(rows[0]["timestamp"] - recent) < 5


def test_prune_preserves_incident_window(db):
    now = time.time()
    protected = now - 40 * 60  # within the incident protected window
    _insert_metrics(db, "metrics_cpu", [protected])
    db.create_incident(
        {
            "detected_at": now, "incident_type": "HARD_HANG", "confidence": "HIGH",
            "previous_session_id": None, "last_metric_timestamp": protected,
            "reboot_timestamp": now, "duration_estimate": None,
            "findings": [], "evidence": [],
        },
        [],
    )
    result = retention.prune_metrics(db, retention_hours=1)
    assert result["deleted_rows"] == 0
    rows = db.query("SELECT COUNT(*) AS n FROM metrics_cpu")
    assert rows[0]["n"] == 1
