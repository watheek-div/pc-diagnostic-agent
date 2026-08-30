"""Boot detection tests."""

from diagnostics.boot_detector import detect_boot

from tests.mocks import (
    boot_6005,
    clean_shutdown_6006,
    kernel_power_41,
    unexpected_shutdown_6008,
)


def test_first_boot_creates_session(db):
    result = detect_boot(db, now=2000.0, boot_time=2000.0)
    assert result["session_id"] == 1
    assert result["previous_boot_time"] is None
    assert result["previous_session_clean"] is None


def test_clean_shutdown_detected(db):
    prev_boot = 1000.0
    db.create_session(prev_boot, 1000.0)
    db.insert_events(
        [
            boot_6005(prev_boot),
            clean_shutdown_6006(1500.0),
        ],
        session_id=1,
    )
    result = detect_boot(db, now=2000.0, boot_time=2000.0)
    assert result["session_id"] == 2
    assert result["previous_session_clean"] is True
    assert result["unexpected_shutdown"] is False

    prev = db.get_session(1)
    assert prev["previous_session_clean"] == 1


def test_unexpected_shutdown_detected(db):
    prev_boot = 1000.0
    db.create_session(prev_boot, 1000.0)
    db.insert_events(
        [boot_6005(prev_boot), unexpected_shutdown_6008(2000.0), kernel_power_41(2000.0)],
        session_id=1,
    )
    result = detect_boot(db, now=2100.0, boot_time=2000.0)
    assert result["unexpected_shutdown"] is True
    assert result["kernel_power_detected"] is True
    assert result["bugcheck_detected"] is False

    prev = db.get_session(1)
    assert prev["unexpected_shutdown"] == 1
    assert prev["kernel_power_detected"] == 1


def test_service_restart_reuses_session(db):
    # First start creates session 1 for this boot.
    first = detect_boot(db, now=1000.0, boot_time=1000.0)
    assert first["session_id"] == 1
    # A service restart within the same OS boot must NOT create a new session.
    result = detect_boot(db, now=1100.0, boot_time=1000.0)
    assert result["session_id"] == 1
    rows = db.query("SELECT * FROM sessions")
    assert len(rows) == 1


def test_real_reboot_after_restart_creates_session(db):
    # Boot 1 at t=1000, then a service restart (reuses session 1),
    # then a genuine reboot at t=2000 -> new session 2.
    detect_boot(db, now=1000.0, boot_time=1000.0)
    restart = detect_boot(db, now=1100.0, boot_time=1000.0)
    assert restart["session_id"] == 1

    db.insert_events(
        [boot_6005(1000.0), clean_shutdown_6006(1990.0)],
        session_id=1,
    )
    reboot = detect_boot(db, now=2000.0, boot_time=2000.0)
    assert reboot["session_id"] == 2
    assert reboot["previous_session_clean"] is True
    assert reboot["previous_boot_time"] == 1000.0
