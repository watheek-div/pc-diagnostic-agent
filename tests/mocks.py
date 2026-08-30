"""Mock event / metric builders for the 10 required diagnostic scenarios.

All timestamps are epoch floats.  These are pure data so tests never touch real
Windows event logs or hardware.
"""

from __future__ import annotations


def ev(timestamp, provider, event_id, level=1, message="", channel="System", record_id=0):
    return {
        "timestamp": timestamp,
        "provider": provider,
        "event_id": event_id,
        "level": level,
        "message": message,
        "channel": channel,
        "record_id": record_id,
        "computer": "TEST-PC",
        "process_id": None,
        "thread_id": None,
    }


def kernel_power_41(ts, record_id=0):
    return ev(ts, "Microsoft-Windows-Kernel-Power", 41, level=1,
              message="The system has rebooted without cleanly shutting down first.",
              record_id=record_id)


def bugcheck_1001(ts, record_id=0):
    return ev(ts, "BugCheck", 1001, level=1,
              message="The computer has rebooted from a bugcheck.",
              record_id=record_id)


def whea(ts, event_id=17, record_id=0):
    return ev(ts, "Microsoft-Windows-WHEA-Logger", event_id, level=1,
              message="A corrected hardware error has occurred.", record_id=record_id)


def disk_error(ts, event_id=51, record_id=0):
    return ev(ts, "Disk", event_id, level=2,
              message="An error was detected on device during a paging operation.",
              record_id=record_id)


def display_error(ts, event_id=4101, record_id=0):
    return ev(ts, "dxgkrnl", event_id, level=2,
              message="Display driver stopped responding and has recovered.",
              record_id=record_id)


def clean_shutdown_6006(ts, record_id=0):
    return ev(ts, "EventLog", 6006, level=3,
              message="The Event log service was stopped.", record_id=record_id)


def unexpected_shutdown_6008(ts, record_id=0):
    return ev(ts, "EventLog", 6008, level=1,
              message="The previous system shutdown at X was unexpected.",
              record_id=record_id)


def boot_6005(ts, record_id=0):
    return ev(ts, "EventLog", 6005, level=3,
              message="The Event log service was started.", record_id=record_id)


def signed_event(ts, provider, event_id, **kwargs):
    """Event whose ID has the high bit set, exactly as pywin32's classic API
    returns it for System-log records (e.g. 1074 -> -2147482574)."""
    return ev(ts, provider, -(0x80000000 - event_id), **kwargs)


def user32_1074(ts, record_id=0):
    return ev(ts, "User32", 1074, level=3,
              message="The process initiated the restart of computer TEST-PC.",
              record_id=record_id)


def kernel_power_other(ts, event_id=109, record_id=0):
    return ev(ts, "Microsoft-Windows-Kernel-Power", event_id, level=1,
              message="The kernel power service is starting.", record_id=record_id)


def processor_power_55(ts, record_id=0):
    return ev(ts, "Microsoft-Windows-Kernel-Processor-Power", 55, level=1,
              message="The Hyper-V logical processor has entered a new state.",
              record_id=record_id)


def kernel_boot_153(ts, record_id=0):
    return ev(ts, "Microsoft-Windows-Kernel-Boot", 153, level=1,
              message="The system is starting.", record_id=record_id)
