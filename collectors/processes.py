"""Top process collector.

Only process name, PID, CPU %, memory usage and the executable path are
captured.  Command-line arguments (which may contain secrets) are deliberately
NOT collected.
"""

from __future__ import annotations

import psutil

from collectors.base import BaseCollector

TOP_N = 10


class ProcessCollector(BaseCollector):
    name = "process"

    def collect(self, now: float, session_id: int) -> dict:
        procs = []
        try:
            for proc in psutil.process_iter(["pid", "name", "cpu_percent", "memory_info", "exe"]):
                try:
                    info = proc.info
                    procs.append(
                        {
                            "pid": info["pid"],
                            "name": info["name"],
                            "cpu_percent": info["cpu_percent"] or 0.0,
                            "memory_bytes": (info["memory_info"].rss if info["memory_info"] else 0),
                            "exe_path": info["exe"],
                        }
                    )
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
        except Exception:
            return {"metrics_process": []}

        top_cpu = sorted(procs, key=lambda p: p["cpu_percent"], reverse=True)[:TOP_N]
        top_mem = sorted(procs, key=lambda p: p["memory_bytes"], reverse=True)[:TOP_N]

        merged = {p["pid"]: p for p in top_cpu + top_mem}
        return {"metrics_process": list(merged.values())}
