"""CPU utilisation collector."""

from __future__ import annotations

import psutil

from collectors.base import BaseCollector


class CpuCollector(BaseCollector):
    name = "cpu"

    def collect(self, now: float, session_id: int) -> dict:
        percent = psutil.cpu_percent(interval=None)
        freq = psutil.cpu_freq()
        frequency = None
        if freq is not None and getattr(freq, "current", None):
            frequency = round(float(freq.current), 2)
        return {
            "metrics_cpu": [
                {
                    "cpu_percent": percent,
                    "cpu_frequency": frequency,
                    "processor_count": psutil.cpu_count(logical=True),
                }
            ]
        }
