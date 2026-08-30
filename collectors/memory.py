"""Memory and pagefile collector."""

from __future__ import annotations

import psutil

from collectors.base import BaseCollector


class MemoryCollector(BaseCollector):
    name = "memory"

    def collect(self, now: float, session_id: int) -> dict:
        vm = psutil.virtual_memory()
        try:
            swap_percent = psutil.swap_memory().percent
        except Exception:
            # Swap counters can be unavailable (e.g. performance counters
            # disabled); degrade gracefully rather than failing the collector.
            swap_percent = None
        return {
            "metrics_memory": [
                {
                    "memory_total": vm.total,
                    "memory_used": vm.used,
                    "memory_available": vm.available,
                    "memory_percent": vm.percent,
                    "swap_percent": swap_percent,
                }
            ]
        }
