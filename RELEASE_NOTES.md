# PC Diagnostic Agent — Release Notes (V1)

## Version
**V1** (Pilot release)

## Build date
2026-08-19

## Python version used for build
Python 3.12.10 (64-bit), built inside a clean virtual environment via `build.ps1`

## Dependency versions (clean environment, from `requirements.txt`)
| Package | Version | Role |
|---|---|---|
| psutil | 7.2.2 | metric collection (CPU, RAM, disk, processes, uptime) |
| PyYAML | 6.0.3 | configuration file parsing |
| pywin32 | 312 | Windows Event Log + Windows Service integration |
| pytest | 8.4.2 | test suite (dev-only) |
| PyInstaller | 6.22.2 | standalone executable bundling (dev-only) |

> Dependency note: the psutil upper bound in `requirements.txt` was updated
> from `<7.0` to `<8.0`. The code uses only long-stable public psutil APIs and
> was validated end-to-end on psutil 7.2.2 (full test suite + live service).

## Test result
**56 passed** (full suite, clean environment) — PASS

## Build result
**PASS** — `dist\pcdiag\pcdiag.exe` produced (onedir bundle, ~2.3 MB). PyInstaller
warnings are benign (POSIX-only optional modules). All runtime dependencies
bundle correctly (`_internal` contains python312.dll, pywintypes312.dll,
win32evtlog.pyd, servicemanager.pyd, psutil, sqlite3, yaml).

## Service result
Installed and verified via `install.ps1`:
- Service name: `PCDiagnosticAgent`
- Start type: **AUTO_START**
- Account: **LocalSystem**
- Binary: `C:\ProgramData\PCDiagnosticAgent\bin\pcdiag.exe`
- State: **RUNNING**
- Data directories created: `bin`, `data`, `logs`, `reports` under
  `C:\ProgramData\PCDiagnosticAgent`
- Metrics collected every 30 s (verified), Windows Event Log tailing is
  incremental with no duplicate record ids, watchdog stable (0 restarts during
  the validation run).

## Known limitations
- **Real-reboot verification is still pending.** The service is configured for
  AUTO_START, but an actual reboot verification must be performed manually in an
  approved test window. (Boot-path logic was validated by simulation.)
- **Event log cleared-channel handling:** System log record ids can reset after
  a log clear. The agent detects this and falls back to timestamp-based
  incremental collection, so it keeps working — but relies on timestamps moving
  forward.
- **First event-log read cap:** each run ingests at most the newest 1,000 System
  events (`MAX_EVENTS_PER_RUN`); older history is not back-filled.
- **Classic Event Log API:** process/thread ids are not exposed for these
  records and are stored as `None`.
- **GPU / temperature data** is best-effort and depends on `nvidia-smi` /
  WMI; if absent, values are reported as unavailable (agent keeps running).
- **Diagnosis is inference, not certainty.** Termination mode (hard hang / BSOD /
  power loss / clean) is reported with LOW/MEDIUM/HIGH confidence only.
- **Local-only by design:** no outbound network connections, no telemetry, no
  cloud. See the final security check in `VALIDATION_REPORT.md`.

## Installation instructions
Prerequisites: a Windows 10/11 machine; **no Python required** on the target.

1. Copy the `pc-diagnostic-agent-v1` folder to the target machine.
2. Right-click PowerShell and choose **Run as administrator**.
3. Navigate to the package folder and run:
   ```powershell
   .\install.ps1
   ```
4. Expected output ends with `Installation complete.` plus a successful
   `Overall health: OK` line.

What `install.ps1` does:
- creates `C:\ProgramData\PCDiagnosticAgent\{bin,data,logs,reports}`;
- copies `dist\pcdiag\*` to `...\bin`;
- installs the auto-start Windows service `PCDiagnosticAgent` (LocalSystem);
- starts the service and runs a status + health check.

Verify the installation:
```powershell
sc.exe query PCDiagnosticAgent    # STATE should be 4 RUNNING
sc.exe qc PCDiagnosticAgent       # START_TYPE 2 AUTO_START, LocalSystem
& 'C:\ProgramData\PCDiagnosticAgent\bin\pcdiag.exe' health
```

## Uninstallation instructions
From an **elevated** PowerShell prompt in the package folder:
```powershell
.\uninstall.ps1            # stops + removes the service, keeps collected data
.\uninstall.ps1 -PurgeData # also deletes C:\ProgramData\PCDiagnosticAgent
```

## Pilot instructions
After the agent has been running through a failure/reboot cycle:

1. Health: `& '...\bin\pcdiag.exe' health`
2. Incidents: `& '...\bin\pcdiag.exe' incidents`
3. Diagnostics (previous session analysis):
   `& '...\bin\pcdiag.exe' diagnostics`
4. Technician HTML report: `& '...\bin\pcdiag.exe' report`
   → written to `C:\ProgramData\PCDiagnosticAgent\reports\report.html`
5. Export bundle: `& '...\bin\pcdiag.exe' export`
   → written to `C:\ProgramData\PCDiagnosticAgent\reports\pcdiag_export_<date>.zip`
6. Data location: `C:\ProgramData\PCDiagnosticAgent\data\agent.db`
7. Service log: `C:\ProgramData\PCDiagnosticAgent\logs\agent.log`

## Release validation references
- `VALIDATION_REPORT.md` — full validation run (tests, build, install, service,
  incident simulation, retention, watchdog, security, resources, regressions).
- Final pilot gate:
  **FINAL RELEASE STATUS: READY FOR PILOT**
  (set on 2026-08-19 after the clean-environment build, tests, packaging,
  installation, service and dependency validation all passed.)
