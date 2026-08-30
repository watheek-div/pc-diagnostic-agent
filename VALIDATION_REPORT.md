# PC Diagnostic Agent — Validation Report

**Date:** 2026-08-19
**Target:** production pilot build (repository)
**Validated by:** automated validation session

> **Status update (initial public release):** The test suite has since grown
> from 56 to **80 tests** with the addition of incident-regression coverage,
> the simulation harness tests and report-terminology consistency tests. The
> current full suite passes (`80 passed`). The report below documents the
> original V1 pilot validation run.

This report summarises the end-to-end validation of the PC Diagnostic Agent for
production use. All validation tasks were executed against the real repository,
the real PyInstaller build, and a live Windows Service installation running the
built executable.

---

## 1. Environment

| Item | Value |
|---|---|
| OS | Windows 10 Pro, Build 19045 (22H2) |
| Host | (redacted) |
| User | (redacted interactive user; service runs as LocalSystem) |
| Python | 3.12.10 (repository `.venv`) |
| Key packages | psutil 7.2.2, pytest 9.1.1, pywin32 312, PyYAML 6.0.3 |
| SQLite | WAL mode agent database |
| Data root | `C:\ProgramData\PCDiagnosticAgent` |

> Note: `requirements.txt` pins `psutil>=5.9.8,<8.0`; the venv resolved
> psutil 7.2.2. All psutil calls used path through the 7.x API without error.

---

## 2. Task Matrix

| # | Task | Result |
|---|---|---|
| 1 | Repository / spec-file inspection | **PASS** |
| 2 | Full automated test suite | **PASS** — 56/56 |
| 3 | Static / import validation (all modules) | **PASS** — 30/30 |
| 4 | Real build (`build.ps1`) | **PASS** |
| 5 | Executable verification | **PASS** |
| 6 | CLI from built executable | **PASS** — 9/9 commands |
| 7 | Windows Service installation | **PASS** (3 issues fixed, see §4) |
| 8 | Incident simulation + HTML report | **PASS** |
| 9 | Reboot / boot-path validation | **PASS (simulated)** — real reboot deferred (§3.8) |
| 10 | Retention | **PASS** |
| 11 | Watchdog | **PASS** |
| 12 | Security review | **PASS** |
| 13 | Resource usage | **PASS** — negligible |
| 14 | Regression review (previously fixed bugs) | **PASS** — 7/7 |

---

## 3. Detailed Results

### 3.1 Repository inspection (Task 1)

All spec-required modules and files were present:

- `agent/` — config, scheduler, lifecycle, main
- `collectors/` — 9 collectors (CPU, memory, disk, GPU, temperature, process,
  uptime, boot_time, windows_events)
- `storage/` — SQLite database, schema + migrations, retention
- `diagnostics/` — boot detection, crash/hang inference, rule engine
- `reports/` — HTML report generator + template
- `watchdog/` — heartbeat + watchdog thread
- `service/` — pywin32 Windows Service
- `cli/` — technician CLI (9 commands)
- `common/` — paths, logging, time, system-info helpers
- `tests/` — unit test suite with mock scenario builders
- `config.yaml`, `requirements.txt`, `pcdiag.py`, `pcdiag.spec`
- `build.ps1`, `install.ps1`, `uninstall.ps1`
- `README.md`, `docs/TROUBLESHOOTING.md`, `docs/example-report.html`

### 3.2 Test suite (Task 2)

```
56 passed
```

Run twice (pre- and post-service-fix, via `build.ps1`) — both green.

### 3.3 Static / import validation (Task 3)

- `python -m compileall` on all Python sources: exit 0, no errors.
- Import validation of every module under `agent`, `cli`, `collectors`,
  `common`, `diagnostics`, `reports`, `service`, `storage`, `watchdog`,
  `tests`: **30 modules, all import cleanly** (pywin32 optional where
  unavailable during CLI runs).

### 3.4 Build (Task 4)

`build.ps1` completes successfully: runs the test suite first, then PyInstaller.

- Artifact: `dist\pcdiag\pcdiag.exe` (onedir, ~2.34 MB)
- `build\pcdiag\warn-pcdiag.txt` contains **only benign** warnings
  (POSIX/optional modules e.g. `grp`, `fcntl`); no missing-HiddenImport for any
  runtime dependency.
- `config.yaml` is copied into the dist bundle.

### 3.5 Executable verification (Task 5)

- Executable launches and responds to `--help`.
- `_internal` runtime contains python312.dll, pywintypes312.dll,
  win32evtlog.pyd, servicemanager.pyd, win32service.pyd, psutil, yaml, sqlite3
  etc. — every runtime dependency is bundled.
- Installed production copy:
  `C:\ProgramData\PCDiagnosticAgent\bin\pcdiag.exe` (2,344,370 bytes).

### 3.6 CLI from built executable (Task 6)

All **9 commands** validated from the built executable against both a scratch
`PCDIAG_HOME` and the live `C:\ProgramData\PCDiagnosticAgent`:

```
status, info, report, incidents, events,
health, diagnostics, export, service
```

- `status`/`health` report correct agent/data state and an **OK** health result
  against the live database.
- `info` returns full system information (CPU, memory, disk, GPU, uptime, boot).
- `report` regenerates `reports\report.html` from the live DB.
- `events --limit 5` returns real Windows System events.
- `export` produces a valid diagnostic ZIP bundle.
- `service` properly reports service state (via the fixed `--startup auto`
  option ordering, §4.3).

### 3.7 Windows Service (Task 7)

Installed with elevated PowerShell via `install.ps1`:

| Property | Value |
|---|---|
| Service name | `PCDiagnosticAgent` |
| Account | LocalSystem |
| Start type | **AUTO_START** (Start Type 2) |
| Binary path | `C:\ProgramData\PCDiagnosticAgent\bin\pcdiag.exe` |
| State | RUNNING (stable across the whole session) |

Live validation while running:

- **Threads/agents** all live: heartbeat updated, sessions recorded,
  Windows events collected, metrics snapshots appended every 30 s (CPU,
  memory, disk, process, uptime, GPU).
- **Watchdog** performed one controlled restart at start-up (stale heartbeat,
  restart 1/5), recorded in `agent_state`, then recovered with no further
  restart — proving the watchdog path through the real service.
- **Event cursor** persists in `agent_state`
  (`event_last_record_id:System`, `event_last_timestamp:System`) and advances;
  **0 duplicate record_ids** across ~1,800+ collected events.
- `agent.log` grows only on meaningful events (280 bytes at measurement time).

Three issues were found and fixed during this task (§4). Re-install + start
verified after each fix.

### 3.8 Boot-path validation (Task 9)

A **real reboot was deferred** per operator decision (the host runs active
services and the validation prompt allowed skipping "if it is not safe"). In
its place, the boot path was validated deterministically:

- **Boot simulation** (`detect_boot` replayed exactly as the service does at
  start-up) with a recovered database containing a prior session that ends in a
  hard hang:
  - New session created; previous session correctly detected and **finalised**
    with `previous_session_clean=0`, `unexpected_shutdown=1`,
    `kernel_power_detected=1`, uptime before boot preserved.
  - Diagnosis produced the expected **HARD_HANG** incident.
- **Cursor-resume control cases** (fake Event Log) covering:
  - (A) fresh agent — full ingest, chronological order;
  - (B) restart with persisted cursor — **only new records appended, no
    duplicate flood**;
  - (C/D) cleared log with reset record ids — records newer than the cursor
    timestamp are still collected, idle runs add nothing;
  - (E) post-clear operation — collection continues seamlessly.
- Cross-checked against the live service: event collection has been running
  continuously across service restarts with **0 duplicate record ids**.

Result: **PASS (simulated)**. Recommend a scheduled real-reboot pass on the
pilot host when an outage window is available.

### 3.9 Incident simulation (Task 8)

Reproduced an incident with mock hardened-hang scenario data through the real
detection pipeline:

- Detected type `HARD_HANG`, confidence `HIGH`, duration estimate ~300 s.
- 9 evidence items surfaced; diagnosis produced findings with severity +
  confidence ratings; facts vs hypotheses clearly separated.
- HTML report generation validated against all simulated content checks.
- Result: **PASS**.

### 3.10 Retention (Task 10)

- `prune_metrics` removed exactly the expired metric rows (2 deleted) and
  preserved all incident-protected rows.
- Incidents / findings tables untouched by pruning.
- Result: **PASS**.

### 3.11 Watchdog (Task 11)

- Fresh heartbeat → no action.
- Stale heartbeat → **1 controlled restart** + failure recorded in
  `agent_state` (`watchdog_failures`, `watchdog_last_failure`).
- Backoff prevents restart loops; `max_restarts` enforced; watchdog can be
  stopped cleanly.
- Result: **PASS**.

### 3.12 Security review (Task 12)

Reviewed all application directories for telemetry / outbound / privacy

- **No outbound network APIs** — no HTTP/SMTP/DNS/socket client usage
  (only `sqlite3.connect` to the local DB and `socket.gethostname()` for the
  host name).
- **No sensitive-data collection** — no browser history, keystroke logging,
  screenshots, webcam/microphone, or credential access. All data is hardware /
  OS health telemetry stored locally.
- Result: **PASS**.

### 3.13 Resource usage (Task 13)

Measured on the running service:

| Metric | Value |
|---|---|
| Working set | ~33 MB |
| CPU (idle) | ~0 % |
| Threads | 4–6 |
| Handles | ~581 |
| DB (data) | 663 KB + WAL |
| Log | ~280 B, grows only on events |

Metric tables grow on schedule; no leaks or unbounded growth observed.

### 3.14 Regression review (Task 14)

Re-verified the 7 previously-fixed defects — all still fixed:

1. Schema migrations idempotent.
2. sqllite Row-dict access pattern correct everywhere.
3. `swap_percent=None` graceful degradation in the memory windowing logic.
4. GPU / temperature collectors fall back to `None` safely.
5. `watchdog.stop()` idempotent/clean.
6. `local_from_epoch` handles pre-epoch timestamps.
7. no re-scan/flood of the event log after restarts (see §3.8).

Result: **PASS — 7/7**.

---

## 4. Issues Found and Fixed

All three were genuine defects surfaced during validation; none are feature
requests.

| # | File | Defect | Fix |
|---|---|---|---|
| 1 | `install.ps1` | Fresh install aborted: script checked the **destination** path (`bin\pcdiag.exe`) for existence before copying, which is false on first install. | Check the source `dist\pcdiag\pcdiag.exe` instead. Verified by a clean reinstall. |
| 2 | `service\windows_service.py` | Service start failed with SCM error **1053**: `run_service_command_line()` always called `HandleCommandLine`, and with no arguments that prints usage and exits — so when the SCM launches `pcdiag.exe` with no args, the process exited before SCM saw a "running" state. | When frozen with no arguments, use `servicemanager.Initialize()`, `PrepareToHostSingle(AgentService)`, `StartServiceCtrlDispatcher()`; otherwise fall back to `HandleCommandLine`. Verified the service now reaches RUNNING. |
| 3 | `cli\commands.py` | Service was installing **DEMAND_START** instead of AUTO_START: `cmd_service` appends `--startup auto` at the **end** of the argv list; getopt stops parsing options at the first positional argument (`install`), so the option was dropped. | Place `--startup auto` **before** the action in `_sys.argv`. Verified with `sc.exe qc` → `START_TYPE: 2 AUTO_START`. |

> These fixes follow the "fix anything that fails, re-run the validation" rule
> from the validation brief. No new functionality was added. The full test
> suite (56) and the build were re-run green afterwards.

---

## 5. Deliverables / Final State

- Source fixes in `install.ps1`, `service\windows_service.py`,
  `cli\commands.py` (upstream; rebuild next release).
- Build artifact: `dist\pcdiag\pcdiag.exe` (+ `_internal` + `config.yaml`).
- Pilot installation live on this host:
  - Service `PCDiagnosticAgent` — AUTO_START, LocalSystem, RUNNING.
  - Data under `C:\ProgramData\PCDiagnosticAgent` (bin, data, logs, reports).
  - `C:\ProgramData\PCDiagnosticAgent\logs\agent.log` for watchdog events.
- All transient validation scripts and logs were placed outside the repository;
  no validation artifacts were added to the repository.

---

## 6. Verdict

The PC Diagnostic Agent build **passes validation** for production pilot use on
this host. All automated tests pass, the executable builds and runs all CLI
commands, the Windows Service installs, auto-starts and runs stably while
continuous telemetry is collected, watchdog, retention, incident detection and
reporting all behave correctly, and the security/resource review found no
concerns.

**One recommended follow-up:** run a real reboot (service auto-start on boot)
in an approved maintenance window, since the physical reboot test was deferred
by operator decision; the boot path was validated by simulation in its place.