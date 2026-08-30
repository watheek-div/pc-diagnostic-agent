"""Regression tests for the false POWER_LOSS classification (real /r /t 10 reboot).

Lock in the fixes for the incident seen in the pilot build:
* normal restarts must never be classified as POWER_LOSS;
* signed (high-bit) event IDs from the classic Event Log API must not hide
  clean-shutdown events;
* Kernel-Power events other than 41 must not count as a power-loss signal;
* Kernel-Processor-Power / Kernel-Boot events must not count as disk errors;
* incident evidence is scoped to the incident window around the reboot.
"""

from diagnostics.boot_detector import detect_boot
from diagnostics.diagnosis import run_diagnosis

from tests.mocks import (
    boot_6005,
    clean_shutdown_6006,
    kernel_boot_153,
    kernel_power_41,
    kernel_power_other,
    processor_power_55,
    signed_event,
    user32_1074,
)

PREV_BOOT = 1000.0
BOOT = 2000.0


def _boot_result(prev_clean=False):
    return {
        "boot_time": BOOT,
        "previous_boot_time": PREV_BOOT,
        "previous_session_id": 1,
        "previous_session_clean": prev_clean,
    }


def _seed_session(db, prev_boot=PREV_BOOT):
    db.create_session(prev_boot, prev_boot)


def _insert_events(db, events):
    db.insert_events(events, session_id=1)


def _incident(result):
    return result["incident"]


# -- A. Normal Windows restart (shutdown /r /t 10) --------------------------
def test_a_normal_restart_not_power_loss(db, config):
    """Realistic /r /t 10 shutdown: User32 1074 + 6006 + routine Kernel-Power."""
    _seed_session(db)
    _insert_events(
        db,
        [
            boot_6005(PREV_BOOT),
            user32_1074(BOOT - 15),
            clean_shutdown_6006(BOOT - 15),
            kernel_power_other(BOOT - 8, 109),
            kernel_power_other(BOOT - 5, 172),
            kernel_power_other(BOOT - 3, 521),
            processor_power_55(BOOT - 10),
            processor_power_55(BOOT - 9),
        ],
    )
    result = run_diagnosis(db, _boot_result(True), config)
    assert result["incident"] is None
    assert result["summary"]["kernel_power_detected"] is False
    assert result["summary"]["disk_error_count"] == 0


def test_a_normal_restart_boot_detection_is_clean(db):
    """detect_boot must mark the previous session clean for the same reboot."""
    _seed_session(db)
    _insert_events(
        db,
        [boot_6005(PREV_BOOT), user32_1074(BOOT - 15), clean_shutdown_6006(BOOT - 15)],
    )
    result = detect_boot(db, now=BOOT, boot_time=BOOT)
    assert result["previous_session_clean"] is True
    assert result["unexpected_shutdown"] is False
    assert result["kernel_power_detected"] is False
    assert result["session_id"] == 2


def test_a_signed_clean_shutdown_ids_still_clean(db, config):
    """High-bit (signed) 6005/1074/6006 from pywin32 must still mean clean."""
    _seed_session(db)
    _insert_events(
        db,
        [
            signed_event(PREV_BOOT, "EventLog", 6005),
            signed_event(BOOT - 15, "User32", 1074),
            signed_event(BOOT - 15, "EventLog", 6006),
            signed_event(BOOT - 8, "Microsoft-Windows-Kernel-Power", 109),
        ],
    )
    result = run_diagnosis(db, _boot_result(True), config)
    assert result["incident"] is None
    assert result["summary"]["kernel_power_detected"] is False


# -- B. Clean shutdown -------------------------------------------------------
def test_b_clean_shutdown_no_incident(db, config):
    _seed_session(db)
    _insert_events(db, [boot_6005(PREV_BOOT), clean_shutdown_6006(BOOT - 15)])
    result = run_diagnosis(db, _boot_result(True), config)
    assert _incident(result) is None


# -- C. Unexpected shutdown (6008) -------------------------------------------
def test_c_unexpected_shutdown_6008_incident(db, config):
    _seed_session(db)
    _insert_events(db, [signed_event(BOOT, "EventLog", 6008)])
    result = run_diagnosis(db, _boot_result(False), config)
    assert _incident(result) is not None
    assert "No clean shutdown event" in _incident(result)["evidence"]


# -- D. Kernel-Power 41 without clean shutdown --------------------------------
def test_d_kernel_power_41_incident(db, config):
    _seed_session(db)
    _insert_events(db, [signed_event(BOOT, "Microsoft-Windows-Kernel-Power", 41)])
    result = run_diagnosis(db, _boot_result(False), config)
    assert _incident(result) is not None
    assert "Kernel-Power 41 detected" in _incident(result)["evidence"]


# -- E. BugCheck --------------------------------------------------------------
def test_e_bugcheck_1001_bsod(db, config):
    _seed_session(db)
    _insert_events(
        db,
        [
            signed_event(
                BOOT,
                "Microsoft-Windows-WER-SystemErrorReporting",
                1001,
                message="The computer has rebooted from a bugcheck.",
            )
        ],
    )
    result = run_diagnosis(db, _boot_result(False), config)
    assert _incident(result)["incident_type"] == "BSOD"
    assert _incident(result)["confidence"] == "HIGH"


# -- F. Possible hard hang ----------------------------------------------------
def test_f_possible_hard_hang(db, config):
    _seed_session(db)
    _insert_events(db, [kernel_power_41(BOOT)])
    db.insert_snapshot(
        {"metrics_cpu": [{"cpu_percent": 40.0, "cpu_frequency": None, "processor_count": 8}]},
        BOOT - 300,
        1,
    )
    result = run_diagnosis(db, _boot_result(False), config)
    assert _incident(result)["incident_type"] == "HARD_HANG"
    assert _incident(result)["confidence"] == "HIGH"


# -- G. Power-loss-like -------------------------------------------------------
def test_g_power_loss_like(db, config):
    _seed_session(db)
    _insert_events(db, [kernel_power_41(BOOT)])
    db.insert_snapshot(
        {"metrics_cpu": [{"cpu_percent": 40.0, "cpu_frequency": None, "processor_count": 8}]},
        BOOT - 5,
        1,
    )
    result = run_diagnosis(db, _boot_result(False), config)
    assert _incident(result)["incident_type"] == "POWER_LOSS"
    assert _incident(result)["confidence"] == "LOW"


# -- Scoping and over-match guards --------------------------------------------
def test_disk_evidence_scoped_to_incident_window(db, config):
    """Events before the incident window must not count as incident evidence."""
    _seed_session(db, prev_boot=100.0)
    _insert_events(
        db,
        [
            signed_event(150.0, "Microsoft-Windows-Kernel-Processor-Power", 55),
            kernel_boot_153(160.0),
            kernel_power_41(BOOT),
        ],
    )
    boot_result = {
        "boot_time": BOOT,
        "previous_boot_time": 100.0,
        "previous_session_id": 1,
        "previous_session_clean": False,
    }
    result = run_diagnosis(db, boot_result, config)
    assert _incident(result) is not None
    assert result["summary"]["disk_error_count"] == 0


def test_ntfs_98_is_disk_when_in_window(db, config):
    _seed_session(db, prev_boot=100.0)
    _insert_events(
        db,
        [
            kernel_power_41(BOOT),
            signed_event(BOOT - 10, "Microsoft-Windows-Ntfs", 98),
        ],
    )
    boot_result = {
        "boot_time": BOOT,
        "previous_boot_time": 100.0,
        "previous_session_id": 1,
        "previous_session_clean": False,
    }
    result = run_diagnosis(db, boot_result, config)
    assert result["summary"]["disk_error_count"] == 1
    assert "POSSIBLE_DISK_PROBLEM" in [f["type"] for f in result["findings"]]
