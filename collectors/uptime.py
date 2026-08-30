"""System uptime / boot-time collector."""

from __future__ import annotations

import psutil

from collectors.base import BaseCollector


class UptimeCollector(BaseCollector):
    name = "uptime"

    def collect(self, now: float, session_id: int) -> dict:
        boot_time = psutil.boot_time()
        return {
            "metrics_uptime": [
                {
                    "boot_time": boot_time,
                    "uptime_seconds": now - boot_time,
                }
            ]
        }
