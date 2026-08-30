"""Event classification tests."""

from diagnostics.event_analyzer import classify_event, summarize

from tests.mocks import (
    bugcheck_1001,
    clean_shutdown_6006,
    disk_error,
    display_error,
    kernel_power_41,
    unexpected_shutdown_6008,
    whea,
)


def test_classify_kernel_power():
    assert classify_event(kernel_power_41(1000)) == "kernel_power"


def test_classify_bugcheck():
    assert classify_event(bugcheck_1001(1000)) == "bugcheck"


def test_classify_whea():
    assert classify_event(whea(1000)) == "whea"


def test_classify_disk():
    assert classify_event(disk_error(1000)) == "disk"


def test_classify_display():
    assert classify_event(display_error(1000)) == "display"


def test_classify_shutdown_clean_and_unexpected():
    assert classify_event(clean_shutdown_6006(1000)) == "shutdown_clean"
    assert classify_event(unexpected_shutdown_6008(1000)) == "shutdown_unexpected"


def test_summarize_counts():
    events = [
        kernel_power_41(1000),
        whea(1001),
        whea(1002),
        whea(1003),
        disk_error(1004),
        display_error(1005),
    ]
    s = summarize(events)
    assert s["kernel_power_count"] == 1
    assert s["whea_count"] == 3
    assert s["disk_error_count"] == 1
    assert s["display_error_count"] == 1
    assert s["kernel_power_detected"] is True
    assert s["bugcheck_detected"] is False
    assert s["clean_shutdown"] is False
