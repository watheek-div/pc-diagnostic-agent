"""GPU telemetry (best-effort, no kernel drivers, no extra Python deps).

Static properties (name, driver version, VRAM) are read via PowerShell
``Get-CimInstance Win32_VideoController``, which is present on Windows 10/11.
Live utilization / temperature / VRAM usage are only available for NVIDIA
cards via ``nvidia-smi`` when it is already installed; otherwise those fields
are ``None`` and the agent continues.
"""

from __future__ import annotations

import json
import shutil
import subprocess

from collectors.base import BaseCollector


class GpuCollector(BaseCollector):
    name = "gpu"

    def collect(self, now: float, session_id: int, db=None) -> dict:
        cards = self._video_controllers()
        nvidia_stats = self._nvidia_smi_stats() if self._has_nvidia_smi() else {}

        rows = []
        for card in cards:
            name = card.get("name")
            stats = nvidia_stats.get(name, {})
            rows.append(
                {
                    "gpu_name": name,
                    "utilization": stats.get("utilization"),
                    "memory_used": stats.get("memory_used"),
                    "memory_total": card.get("adapter_ram") or stats.get("memory_total"),
                    "temperature_c": stats.get("temperature_c"),
                    "driver_version": card.get("driver_version"),
                }
            )
        return {"metrics_gpu": rows}

    @staticmethod
    def _video_controllers() -> list[dict]:
        script = (
            "Get-CimInstance Win32_VideoController | "
            "Select-Object Name,DriverVersion,AdapterRAM | ConvertTo-Json -Compress"
        )
        out = _run_powershell(script)
        if not out:
            return []
        try:
            data = json.loads(out)
        except json.JSONDecodeError:
            return []
        if isinstance(data, dict):
            data = [data]
        cards = []
        for item in data:
            if not isinstance(item, dict):
                continue
            cards.append(
                {
                    "name": item.get("Name"),
                    "driver_version": item.get("DriverVersion"),
                    "adapter_ram": _to_int(item.get("AdapterRAM")),
                }
            )
        return cards

    @staticmethod
    def _has_nvidia_smi() -> bool:
        return shutil.which("nvidia-smi") is not None

    @staticmethod
    def _nvidia_smi_stats() -> dict:
        try:
            out = subprocess.run(
                [
                    "nvidia-smi",
                    "--query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu",
                    "--format=csv,noheader,nounits",
                ],
                capture_output=True,
                text=True,
                timeout=5,
            )
        except (OSError, subprocess.SubprocessError):
            return {}
        stats = {}
        for line in out.stdout.splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) < 5:
                continue
            stats[parts[0]] = {
                "utilization": _to_float(parts[1]),
                "memory_used": _mb_to_bytes(parts[2]),
                "memory_total": _mb_to_bytes(parts[3]),
                "temperature_c": _to_float(parts[4]),
            }
        return stats


def _run_powershell(script: str) -> str:
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            text=True,
            timeout=15,
        )
        return out.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def _to_float(value: str | None) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _mb_to_bytes(value: str | None) -> int | None:
    f = _to_float(value)
    if f is None:
        return None
    return int(f * 1024 * 1024)
