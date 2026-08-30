"""Database layer tests."""

from storage.database import Database


def test_schema_created(db):
    rows = db.query("SELECT name FROM sqlite_master WHERE type='table'")
    names = {r["name"] for r in rows}
    for table in ("sessions", "events", "incidents", "findings", "heartbeat", "metrics_cpu", "metrics_memory"):
        assert table in names


def test_insert_snapshot(db):
    n = db.insert_snapshot(
        {"metrics_cpu": [{"cpu_percent": 12.5, "cpu_frequency": 3400.0, "processor_count": 8}]},
        timestamp=1000.0,
        session_id=1,
    )
    assert n == 1
    rows = db.query("SELECT * FROM metrics_cpu")
    assert rows[0]["cpu_percent"] == 12.5
    assert rows[0]["timestamp"] == 1000.0
    assert rows[0]["session_id"] == 1


def test_insert_snapshot_ignores_unknown_table(db):
    n = db.insert_snapshot({"not_a_table": [{"x": 1}]}, 1000.0, 1)
    assert n == 0


def test_insert_events_and_clip_message(db):
    long_msg = "A" * 5000
    db.insert_events(
        [{"timestamp": 1000.0, "provider": "Test", "event_id": 1, "level": 2, "message": long_msg}],
        session_id=1,
    )
    rows = db.query("SELECT message FROM events")
    assert len(rows[0]["message"]) <= 4000


def test_sessions_roundtrip(db):
    sid = db.create_session(1000.0, 1000.0)
    db.update_session(sid, previous_boot_time=900.0, previous_session_clean=1)
    session = db.get_session(sid)
    assert session["previous_boot_time"] == 900.0
    assert session["previous_session_clean"] == 1
    assert db.latest_session()["session_id"] == sid


def test_heartbeat_roundtrip(db):
    assert db.get_heartbeat() is None
    db.update_heartbeat(1234.5)
    assert db.get_heartbeat() == 1234.5
    db.update_heartbeat(9999.0)
    assert db.get_heartbeat() == 9999.0


def test_state_roundtrip(db):
    db.set_state("event_last_record_id:System", "42")
    assert db.get_state("event_last_record_id:System") == "42"
    db.set_state("event_last_record_id:System", "43")
    assert db.get_state("event_last_record_id:System") == "43"


def test_incident_and_findings(db):
    incident = {
        "detected_at": 1000.0, "incident_type": "HARD_HANG", "confidence": "HIGH",
        "previous_session_id": 1, "last_metric_timestamp": 950.0,
        "reboot_timestamp": 1000.0, "duration_estimate": 50.0,
        "findings": ["POSSIBLE_HARD_HANG"], "evidence": ["no clean shutdown"],
    }
    findings = [{
        "type": "POSSIBLE_HARD_HANG", "severity": "HIGH", "confidence": "HIGH",
        "evidence": ["no clean shutdown"], "timestamp": 1000.0, "explanation": "hard hang",
    }]
    incident_id = db.create_incident(incident, findings)
    assert db.get_incident(incident_id)["incident_type"] == "HARD_HANG"
    found = db.list_findings(incident_id)
    assert found[0]["finding_type"] == "POSSIBLE_HARD_HANG"
