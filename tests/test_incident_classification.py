"""End-to-end incident classification tests (scenarios from the spec)."""

from diagnostics.diagnosis import run_diagnosis

from tests.mocks import (
    boot_6005,
    bugcheck_1001,
    clean_shutdown_6006,
    disk_error,
    display_error,
    kernel_power_41,
    whea,
)

PREV_BOOT = 1000.0
BOOT = 2000.0


def _boot_result(prev_clean):
    return {
        "boot_time": BOOT,
        "previous_boot_time": PREV_BOOT,
        "previous_session_id": 1,
        "previous_session_clean": prev_clean,
    }


def _seed_session(db):
    db.create_session(PREV_BOOT, PREV_BOOT)


def _insert_events(db, events):
    db.insert_events(events, session_id=1)


def _metric(db, table, row, ts):
    db.insert_snapshot({table: [row]}, ts, 1)


def _findings(result):
    return [f["type"] for f in result.get("findings", [])]


def test_normal_shutdown_no_incident(db, config):
    _seed_session(db)
    _insert_events(db, [boot_6005(PREV_BOOT), clean_shutdown_6006(1500.0)])
    result = run_diagnosis(db, _boot_result(True), config)
    assert result["incident"] is None


def test_bugcheck_produces_bsod(db, config):
    _seed_session(db)
    _insert_events(db, [bugcheck_1001(BOOT)])
    result = run_diagnosis(db, _boot_result(False), config)
    assert result["incident"] is not None
    assert result["incident"]["incident_type"] == "BSOD"
    assert result["incident"]["confidence"] == "HIGH"


def test_kernel_power_41_produces_incident(db, config):
    _seed_session(db)
    _insert_events(db, [kernel_power_41(BOOT)])
    result = run_diagnosis(db, _boot_result(False), config)
    assert result["incident"] is not None
    assert "no clean shutdown event" in [e.lower() for e in result["incident"]["evidence"]]


def test_whea_produces_hardware_finding(db, config):
    _seed_session(db)
    _insert_events(db, [kernel_power_41(BOOT), whea(BOOT - 10), whea(BOOT - 9), whea(BOOT - 8)])
    result = run_diagnosis(db, _boot_result(False), config)
    assert "POSSIBLE_HARDWARE_ERROR" in _findings(result)


def test_disk_errors_produce_disk_finding(db, config):
    _seed_session(db)
    _insert_events(db, [kernel_power_41(BOOT), disk_error(BOOT - 20)])
    result = run_diagnosis(db, _boot_result(False), config)
    assert "POSSIBLE_DISK_PROBLEM" in _findings(result)


def test_display_errors_produce_gpu_finding(db, config):
    _seed_session(db)
    _insert_events(db, [kernel_power_41(BOOT), display_error(BOOT - 20)])
    result = run_diagnosis(db, _boot_result(False), config)
    assert "POSSIBLE_GPU_PROBLEM" in _findings(result)


def test_high_memory_produces_memory_finding(db, config):
    _seed_session(db)
    _insert_events(db, [kernel_power_41(BOOT)])
    _metric(db, "metrics_memory", {"memory_percent": 95.0}, 1500.0)
    result = run_diagnosis(db, _boot_result(False), config)
    assert "POSSIBLE_MEMORY_PRESSURE" in _findings(result)


def test_high_cpu_produces_cpu_finding(db, config):
    _seed_session(db)
    _insert_events(db, [kernel_power_41(BOOT)])
    _metric(db, "metrics_cpu", {"cpu_percent": 99.0, "cpu_frequency": None, "processor_count": 8}, 1500.0)
    result = run_diagnosis(db, _boot_result(False), config)
    assert "POSSIBLE_CPU_PRESSURE" in _findings(result)


def test_high_temperature_produces_thermal_finding(db, config):
    _seed_session(db)
    _insert_events(db, [kernel_power_41(BOOT)])
    _metric(db, "metrics_temperature", {"sensor": "cpu", "temperature_c": 97.0}, 1500.0)
    result = run_diagnosis(db, _boot_result(False), config)
    assert "POSSIBLE_THERMAL_PROBLEM" in _findings(result)


def test_possible_hard_hang_high(db, config):
    _seed_session(db)
    _insert_events(db, [kernel_power_41(BOOT)])
    # Metrics stopped 5 minutes before reboot.
    _metric(db, "metrics_cpu", {"cpu_percent": 40.0, "cpu_frequency": None, "processor_count": 8}, 1700.0)
    result = run_diagnosis(db, _boot_result(False), config)
    assert result["incident"]["incident_type"] == "HARD_HANG"
    assert result["incident"]["confidence"] == "HIGH"
    assert "POSSIBLE_HARD_HANG" in _findings(result)


def test_unknown_incident_insufficient_evidence(db, config):
    _seed_session(db)
    _insert_events(db, [kernel_power_41(BOOT)])
    # No metrics, no additional events -> low confidence but still an incident.
    result = run_diagnosis(db, _boot_result(False), config)
    assert result["incident"] is not None


def test_duplicate_incident_not_created(db, config):
    _seed_session(db)
    _insert_events(db, [kernel_power_41(BOOT)])
    first = run_diagnosis(db, _boot_result(False), config)
    second = run_diagnosis(db, _boot_result(False), config)
    assert first["incident"]["incident_id"] is not None
    assert "incident_id" not in second["incident"]
    incidents = db.list_incidents()
    assert len(incidents) == 1
