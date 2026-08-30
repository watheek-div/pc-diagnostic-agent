"""Deterministic synthetic incident scenarios.

Every scenario describes a complete previous session: a boot time, metrics
sampled every 30 seconds, heartbeat timestamps, and the Windows event evidence
that the real engine consumes.  Timestamps are fixed constants so the harness
is fully reproducible and does not depend on the real Windows Event Log.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

# Fixed synthetic timeline start (10:00:00 UTC on a known date).  All scenario
# times are offsets from this constant so runs are byte-for-byte reproducible.
T0 = int(datetime(2026, 8, 19, 10, 0, 0, tzinfo=timezone.utc).timestamp())

COLLECTION_INTERVAL = 30

HARD_HANG = "hard-hang"
POWER_LOSS = "power-loss"
BSOD = "bsod"
NORMAL_RESTART = "normal-restart"

MACHINE = "SIM-PC"


@dataclass(frozen=True)
class Scenario:
    name: str
    expected_type: str | None
    expected_confidence: str | None
    prev_boot: float
    boot: float
    last_activity: float | None
    description: str
    events: list[dict] = field(default_factory=list)
    snapshots: list[tuple[float, dict]] = field(default_factory=list)
    heartbeats: list[float] = field(default_factory=list)


def _event(ts: float, provider: str, event_id: int, level: int, message: str,
           record_id: int = 0) -> dict:
    return {
        "timestamp": ts,
        "provider": provider,
        "event_id": event_id,
        "level": level,
        "channel": "System",
        "record_id": record_id,
        "message": message,
        "computer": MACHINE,
        "process_id": None,
        "thread_id": None,
    }


def _cpu(pct: float) -> dict:
    return {"cpu_percent": pct, "cpu_frequency": 2400.0, "processor_count": 8}


def _mem(pct: float) -> dict:
    return {"memory_percent": pct, "memory_total": 17179869184.0, "memory_used": 0.0,
            "memory_available": 0.0, "swap_percent": 30.0}


def _disk(pct: float) -> dict:
    return {"device": "C:", "mountpoint": "C:\\", "total": 512_000_000_000.0,
            "used": 0.0, "free": 0.0, "percent": pct, "read_bytes": 0.0,
            "write_bytes": 0.0, "read_latency_ms": 0.0, "write_latency_ms": 0.0,
            "disk_model": "SIM SSD", "disk_type": "ssd"}


def _process(pct: float) -> dict:
    return {"pid": 1000, "name": "chrome.exe", "cpu_percent": pct * 0.8,
            "memory_bytes": 1_200_000_000,
            "exe_path": "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe"}


def _metric_rows(prev_boot: float, ts: float, cpu_pct: float, mem_pct: float,
                 disk_pct: float, temp_c: float) -> dict:
    return {
        "metrics_cpu": [_cpu(cpu_pct)],
        "metrics_memory": [_mem(mem_pct)],
        "metrics_disk": [_disk(disk_pct)],
        "metrics_uptime": [{"boot_time": prev_boot, "uptime_seconds": ts - prev_boot}],
        "metrics_process": [_process(cpu_pct)],
        "metrics_temperature": [{"sensor": "cpu", "temperature_c": temp_c}],
    }


def _metric_stream(prev_boot: float, start: float, end: float,
                   cpu_fn, mem_fn, disk_fn, temp_fn) -> list[tuple[float, dict]]:
    snapshots = []
    ts = start
    while ts <= end + 1e-6:
        snapshots.append(
            (ts, _metric_rows(prev_boot, ts, cpu_fn(ts), mem_fn(ts), disk_fn(ts), temp_fn(ts)))
        )
        ts += COLLECTION_INTERVAL
    return snapshots


def _heartbeat_stream(start: float, end: float) -> list[float]:
    values = []
    ts = start
    while ts <= end + 1e-6:
        values.append(ts)
        ts += COLLECTION_INTERVAL
    return values


def _boot_events(boot: float, kp41: bool = False, bugcheck: bool = False,
                 user_initiated_restart: bool = True) -> list[dict]:
    """Events stamped at/just after the synthetic current boot."""
    events = [
        _event(boot + 4, "EventLog", 6009, 3, "Microsoft (R) Windows (R) 10 Enterprise."),
        _event(boot + 4, "EventLog", 6005, 3, "The Event log service was started."),
        _event(boot + 4, "EventLog", 6013, 3, "The system uptime is 0 seconds."),
    ]
    if kp41:
        events.append(
            _event(boot, "Microsoft-Windows-Kernel-Power", 41, 1,
                   "The system has rebooted without cleanly shutting down first.")
        )
    if bugcheck:
        events.append(
            _event(boot, "BugCheck", 1001, 1,
                   "The computer has rebooted from a bugcheck. The bugcheck was: 0x0000007e.")
        )
    # Routine (non-41) Kernel-Power events are common at every boot.
    events.append(_event(boot + 7, "Microsoft-Windows-Kernel-Power", 109, 1,
                         "The kernel power service has entered the running state."))
    if user_initiated_restart:
        # The shutdown was explicitly requested far before any hard stop.
        events.append(
            _event(boot - 15, "User32", 1074, 3,
                   "The process C:\\Windows\\System32\\shutdown.exe initiated the restart "
                   "of computer SIM-PC on behalf of user SIM\\admin for reason: "
                   "No title for this reason could be found.")
        )
    return events


# --------------------------------------------------------------------------
# hard-hang: metrics stop 5 minutes (300s) before boot.  gap >= 5*interval
# --------------------------------------------------------------------------
def _hard_hang() -> Scenario:
    prev_boot = T0
    boot = T0 + 1560  # +26 minutes => current boot at 10:26
    last_activity = T0 + 1260  # last heartbeat/metric at 10:21

    def cpu(ts):
        elapsed = ts - T0
        if elapsed < 600:
            return 35.0
        if elapsed < 900:
            return 50.0
        if elapsed < 1200:
            return 65.0
        return 91.0

    def mem(ts):
        elapsed = ts - T0
        return 55.0 + min(elapsed / 1200.0, 1.0) * 17.0

    def disk(ts):
        return 100.0 if ts - T0 >= 1230 else 42.0

    def temp(ts):
        return 52.0 + min((ts - T0) / 1560.0, 1.0) * 11.0

    events = _boot_events(boot, kp41=True, user_initiated_restart=False)
    events.append(_event(prev_boot + 2, "EventLog", 6005, 3, "The Event log service was started."))

    return Scenario(
        name=HARD_HANG,
        expected_type="HARD_HANG",
        expected_confidence="HIGH",
        prev_boot=prev_boot,
        boot=boot,
        last_activity=last_activity,
        description=(
            "Metrics collected every 30s from 10:00. Load climbs to CPU 91% at "
            "10:20 and disk reaches 100% at 10:20:30. Last heartbeat 10:21:00, "
            "nothing after 10:21:30; system back at 10:26 with Kernel-Power 41 "
            "and no clean-shutdown event, no BugCheck."
        ),
        events=events,
        snapshots=_metric_stream(prev_boot, T0, last_activity, cpu, mem, disk, temp),
        heartbeats=_heartbeat_stream(T0, last_activity),
    )


# --------------------------------------------------------------------------
# power-loss: metrics/heartbeat stop 5 seconds before boot (abrupt cut).
# --------------------------------------------------------------------------
def _power_loss() -> Scenario:
    prev_boot = T0
    boot = T0 + 1260  # current boot at 10:21
    last_activity = boot - 5  # abrupt stop essentially at reboot time

    def cpu(ts):
        return 35.0

    def mem(ts):
        return 58.0

    def disk(ts):
        return 40.0

    def temp(ts):
        return 51.0

    events = _boot_events(boot, kp41=True, user_initiated_restart=False)
    events.append(_event(prev_boot + 2, "EventLog", 6005, 3, "The Event log service was started."))

    return Scenario(
        name=POWER_LOSS,
        expected_type="POWER_LOSS",
        expected_confidence="LOW",
        prev_boot=prev_boot,
        boot=boot,
        last_activity=last_activity,
        description=(
            "Steady metrics until 10:20:55, then nothing further. No shutdown "
            "event, no BugCheck, Kernel-Power 41 present: consistent with an "
            "abrupt power cut rather than a prolonged freeze."
        ),
        events=events,
        snapshots=_metric_stream(prev_boot, T0, last_activity, cpu, mem, disk, temp),
        heartbeats=_heartbeat_stream(T0, last_activity),
    )


# --------------------------------------------------------------------------
# bsod: BugCheck 1001 recorded at boot.
# --------------------------------------------------------------------------
def _bsod() -> Scenario:
    prev_boot = T0
    boot = T0 + 1200  # current boot at 10:20
    last_activity = boot - 240

    def cpu(ts):
        return 40.0

    def mem(ts):
        return 60.0

    def disk(ts):
        return 45.0

    def temp(ts):
        return 50.0

    events = _boot_events(boot, bugcheck=True, user_initiated_restart=False)
    events.append(_event(prev_boot + 2, "EventLog", 6005, 3, "The Event log service was started."))

    return Scenario(
        name=BSOD,
        expected_type="BSOD",
        expected_confidence="HIGH",
        prev_boot=prev_boot,
        boot=boot,
        last_activity=last_activity,
        description=(
            "BugCheck 1001 recorded at boot (0x0000007e). A live dump event "
            "constitutes direct crash evidence independent of the metric gap."
        ),
        events=events,
        snapshots=_metric_stream(prev_boot, T0, last_activity, cpu, mem, disk, temp),
        heartbeats=_heartbeat_stream(T0, last_activity),
    )


# --------------------------------------------------------------------------
# normal-restart: User32 1074 + EventLog 6006 (clean shutdown), no 41/6008/1001.
# --------------------------------------------------------------------------
def _normal_restart() -> Scenario:
    prev_boot = T0
    boot = T0 + 1500  # current boot at 10:25
    last_activity = boot - 30

    def cpu(ts):
        return 25.0

    def mem(ts):
        return 50.0

    def disk(ts):
        return 38.0

    def temp(ts):
        return 48.0

    events = [
        _event(prev_boot + 2, "EventLog", 6005, 3, "The Event log service was started."),
        _event(boot - 15, "User32", 1074, 3,
               "User SIM\\admin initiated the restart of computer SIM-PC "
               "(shutdown /r /t 10)."),
        _event(boot - 15, "EventLog", 6006, 3, "The Event log service was stopped."),
        _event(boot - 8, "Microsoft-Windows-Kernel-Power", 109, 1,
               "The kernel power service is preparing to stop."),
        _event(boot - 6, "Microsoft-Windows-Kernel-Power", 172, 1,
               "The kernel power service runtime is finishing."),
        _event(boot - 4, "Microsoft-Windows-Kernel-Power", 521, 1,
               "The kernel power service is in the resume path."),
        _event(boot + 4, "EventLog", 6009, 3, "Microsoft (R) Windows (R) 10 Enterprise."),
        _event(boot + 4, "EventLog", 6005, 3, "The Event log service was started."),
        _event(boot + 4, "EventLog", 6013, 3, "The system uptime is 0 seconds."),
        _event(boot + 7, "Microsoft-Windows-Kernel-Power", 109, 1,
               "The kernel power service has entered the running state."),
    ]

    return Scenario(
        name=NORMAL_RESTART,
        expected_type=None,
        expected_confidence=None,
        prev_boot=prev_boot,
        boot=boot,
        last_activity=last_activity,
        description=(
            "A routine restart: User32 1074 (shutdown /r /t 10) followed by "
            "EventLog 6006 (clean shutdown) 15s before boot, and no "
            "Kernel-Power 41 / 6008 / BugCheck. Must be classified as a normal "
            "restart with NO incident."
        ),
        events=events,
        snapshots=_metric_stream(prev_boot, T0, last_activity, cpu, mem, disk, temp),
        heartbeats=_heartbeat_stream(T0, last_activity),
    )


_SCENARIOS: dict[str, Scenario] = {
    HARD_HANG: _hard_hang(),
    POWER_LOSS: _power_loss(),
    BSOD: _bsod(),
    NORMAL_RESTART: _normal_restart(),
}


def scenario_names() -> list[str]:
    return list(_SCENARIOS)


def get_scenario(name: str) -> Scenario:
    if name not in _SCENARIOS:
        raise KeyError(
            f"unknown scenario {name!r}; expected one of {sorted(_SCENARIOS)}"
        )
    return _SCENARIOS[name]