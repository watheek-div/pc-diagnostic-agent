"""Hard-hang inference tests."""

from diagnostics.crash_detector import detect_crash
from diagnostics.hang_detector import infer_termination


def _crash(clean=False, bugcheck=False, kp41=False, unexpected_event=False):
    return detect_crash(
        {
            "bugcheck_detected": bugcheck,
            "kernel_power_detected": kp41,
            "unexpected_shutdown_event": unexpected_event,
        },
        clean,
    )


def test_normal_shutdown():
    crash = _crash(clean=True)
    result = infer_termination(crash, last_activity_timestamp=None, reboot_timestamp=2000.0, collection_interval=30)
    assert result.probable_normal_shutdown is True
    assert result.confidence == "HIGH"


def test_bugcheck_is_crash():
    crash = _crash(bugcheck=True)
    result = infer_termination(crash, last_activity_timestamp=None, reboot_timestamp=2000.0, collection_interval=30)
    assert result.probable_crash is True
    assert result.confidence == "HIGH"


def test_hard_hang_high_confidence_with_long_gap():
    # Activity stopped 5 minutes before reboot -> prolonged freeze.
    crash = _crash(kp41=True)
    result = infer_termination(
        crash, last_activity_timestamp=1700.0, reboot_timestamp=2000.0, collection_interval=30
    )
    assert result.probable_hard_hang is True
    assert result.confidence == "HIGH"
    assert result.hang_gap_seconds == 300.0


def test_power_loss_with_instant_stop():
    # Activity continued until just before reboot -> abrupt cut.
    crash = _crash(kp41=True)
    result = infer_termination(
        crash, last_activity_timestamp=1995.0, reboot_timestamp=2000.0, collection_interval=30
    )
    assert result.probable_power_loss is True
    assert result.confidence == "LOW"


def test_insufficient_evidence_when_no_signals():
    crash = _crash(clean=False)
    result = infer_termination(crash, last_activity_timestamp=None, reboot_timestamp=2000.0, collection_interval=30)
    assert result.probable_hard_hang is False
    assert result.probable_power_loss is False
    assert result.probable_crash is False
    assert result.probable_normal_shutdown is False
