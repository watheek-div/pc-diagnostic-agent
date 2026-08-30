"""Temperature collector (best-effort only).

There is no reliable user-mode API for CPU / motherboard / storage temperatures
on Windows.  This collector reports NVIDIA GPU temperature via ``nvidia-smi``
when available and otherwise returns ``unavailable``.  It never installs kernel
drivers.
"""

from __future__ import annotations

from collectors.base import BaseCollector


class TemperatureCollector(BaseCollector):
    name = "temperature"

    def collect(self, now: float, session_id: int, db=None) -> dict:
        rows = []
        for name, temp in self._nvidia_temperatures().items():
            rows.append({"sensor": f"gpu:{name}", "temperature_c": temp})
        return {"metrics_temperature": rows}

    @staticmethod
    def _nvidia_temperatures() -> dict:
        import shutil
        import subprocess

        if shutil.which("nvidia-smi") is None:
            return {}
        try:
            out = subprocess.run(
                [
                    "nvidia-smi",
                    "--query-gpu=name,temperature.gpu",
                    "--format=csv,noheader,nounits",
                ],
                capture_output=True,
                text=True,
                timeout=5,
            )
        except (OSError, subprocess.SubprocessError):
            return {}
        temps = {}
        for line in out.stdout.splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) < 2:
                continue
            try:
                temps[parts[0]] = float(parts[1])
            except ValueError:
                continue
        return temps
