"""Windows Service implementation (pywin32).

Installed as an auto-start service running as LocalSystem, so it runs before
any user logs in and requires no console window.

Usage (via ``pcdiag service ...`` or directly):
    pcdiag-service.exe install
    pcdiag-service.exe start
    pcdiag-service.exe stop
    pcdiag-service.exe remove
"""

from __future__ import annotations

import sys
import threading

import servicemanager
import win32event
import win32service
import win32serviceutil

from agent.main import run_agent

SERVICE_NAME = "PCDiagnosticAgent"
SERVICE_DISPLAY_NAME = "PC Diagnostic Agent"
SERVICE_DESCRIPTION = (
    "Collects local diagnostic data to investigate PC freezes, hangs and "
    "unexpected restarts. Runs locally only; no network access."
)


class AgentService(win32serviceutil.ServiceFramework):
    _svc_name_ = SERVICE_NAME
    _svc_display_name_ = SERVICE_DISPLAY_NAME
    _svc_description_ = SERVICE_DESCRIPTION

    def __init__(self, args):
        super().__init__(args)
        self.stop_event = threading.Event()

    def SvcStop(self):
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        self.stop_event.set()

    def SvcDoRun(self):
        servicemanager.LogMsg(
            servicemanager.EVENTLOG_INFORMATION_TYPE,
            servicemanager.PYS_SERVICE_STARTED,
            (self._svc_name_, ""),
        )
        try:
            run_agent(stop_event=self.stop_event)
        except Exception as exc:  # noqa: BLE001
            servicemanager.LogErrorMsg(f"{self._svc_name_} failed: {exc}")
        finally:
            self.ReportServiceStatus(win32service.SERVICE_STOPPED)


def run_service_command_line():
    if getattr(sys, "frozen", False) and len(sys.argv) <= 1:
        # Launched by the Windows Service Control Manager (frozen build, no
        # command-line arguments).  Host the service and connect to the SCM
        # dispatcher instead of treating this as an interactive command.
        servicemanager.Initialize()
        servicemanager.PrepareToHostSingle(AgentService)
        servicemanager.StartServiceCtrlDispatcher()
    else:
        win32serviceutil.HandleCommandLine(AgentService)


if __name__ == "__main__":
    run_service_command_line()
