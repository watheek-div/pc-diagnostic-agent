"""Filesystem path helpers.

The default data root lives under ``C:\\ProgramData`` so the agent never writes
into a user profile.  The root can be overridden with the ``PCDIAG_HOME``
environment variable, which is useful for development and for the automated
test suite (so tests never touch the real system directories).
"""

from __future__ import annotations

import os
import sys

APP_NAME = "PCDiagnosticAgent"

DEFAULT_DATA_ROOT = r"C:\ProgramData\PCDiagnosticAgent"


def _data_root() -> str:
    override = os.environ.get("PCDIAG_HOME")
    if override:
        return os.path.abspath(override)
    if sys.platform == "win32":
        return DEFAULT_DATA_ROOT
    # Non-Windows fallback (tests / development only).
    return os.path.join(os.path.expanduser("~"), ".pcdiagnosticagent")


def data_root() -> str:
    return _data_root()


def data_dir() -> str:
    return os.path.join(_data_root(), "data")


def test_data_dir() -> str:
    """Isolated workspace for the ``simulate-incident`` harness.

    Deliberately NOT under ``data`` so a simulation can never collide with or
    overwrite the live production database (``data/agent.db``).
    """
    return os.path.join(_data_root(), "test-data")


def logs_dir() -> str:
    return os.path.join(_data_root(), "logs")


def reports_dir() -> str:
    return os.path.join(_data_root(), "reports")


def database_path() -> str:
    return os.path.join(data_dir(), "agent.db")


def log_file_path() -> str:
    return os.path.join(logs_dir(), "agent.log")


def heartbeat_file_path() -> str:
    return os.path.join(data_dir(), "heartbeat.txt")


def ensure_directories() -> None:
    for path in (data_dir(), logs_dir(), reports_dir()):
        os.makedirs(path, exist_ok=True)
