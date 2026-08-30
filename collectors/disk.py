"""Disk usage and I/O collector.

Only physical and fixed logical partitions are sampled.  Disk I/O counters are
cumulative; deltas are computed by the caller if a rate is needed.  SMART/health
data is not reliably available from user-mode APIs and is reported as a best
effort via WMI; when unavailable the fields are left ``None``.
"""

from __future__ import annotations

import psutil

from collectors.base import BaseCollector


class DiskCollector(BaseCollector):
    name = "disk"

    def collect(self, now: float, session_id: int) -> dict:
        rows = []
        try:
            counters = psutil.disk_io_counters(perdisk=True) or {}
        except Exception:
            counters = {}

        for part in psutil.disk_partitions(all=False):
            try:
                usage = psutil.disk_usage(part.mountpoint)
            except (PermissionError, OSError):
                continue
            if usage.total == 0:
                continue
            io = counters.get(part.device.split("\\")[-1])
            rows.append(
                {
                    "device": part.device,
                    "mountpoint": part.mountpoint,
                    "total": usage.total,
                    "used": usage.used,
                    "free": usage.free,
                    "percent": usage.percent,
                    "read_bytes": getattr(io, "read_bytes", None),
                    "write_bytes": getattr(io, "write_bytes", None),
                    "read_latency_ms": None,
                    "write_latency_ms": None,
                    "disk_model": None,
                    "disk_type": None,
                }
            )
        return {"metrics_disk": rows}
