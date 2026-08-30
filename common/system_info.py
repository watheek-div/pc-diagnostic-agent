"""Static system inventory.

Collected once (and periodically) so the diagnostic report can describe the
machine even when no metric history exists.  All access is best-effort and must
never raise out of this module.
"""

from __future__ import annotations

import platform
import socket


def collect_system_info() -> dict:
    info: dict = {}
    try:
        info["hostname"] = socket.gethostname()
    except OSError:
        info["hostname"] = "unknown"
    try:
        info["platform"] = platform.platform()
    except Exception:
        info["platform"] = platform.system()
    info["machine"] = platform.machine()
    info["python_version"] = platform.python_version()
    info["os"] = platform.system()
    info["os_release"] = platform.release()
    info["os_version"] = platform.version()

    try:
        import psutil

        vm = psutil.virtual_memory()
        info["total_ram_gb"] = round(vm.total / (1024 ** 3), 2)
        info["cpu_count_logical"] = psutil.cpu_count(logical=True)
        info["cpu_count_physical"] = psutil.cpu_count(logical=False)
        info["cpu_model"] = _cpu_model()
        info["boot_time"] = psutil.boot_time()
    except Exception:
        pass

    return info


def _cpu_model() -> str:
    try:
        import psutil

        freq = psutil.cpu_freq()
        brand = platform.processor() or platform.machine()
        if freq and getattr(freq, "max", None):
            return f"{brand} @ {freq.max / 1000:.2f} GHz"
        return brand
    except Exception:
        return platform.processor() or platform.machine()
