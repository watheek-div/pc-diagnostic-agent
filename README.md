# PC Diagnostic Agent

A local-only Windows diagnostic agent that runs as an auto-start Windows service,
continuously collects system health signals, analyzes the Windows Event Log and
diagnostic telemetry, detects abnormal reboot/shutdown patterns, classifies
incidents, and generates technician-friendly HTML diagnostic reports.

The goal is **evidence collection and inference** after the fact: if a PC freezes,
hard-hangs, blue-screens or restarts unexpectedly, a technician can return later
and see what the machine was doing immediately before the failure — without having
been present when it happened.

Diagnostic conclusions are always presented as **hypotheses with confidence
levels**, never as guaranteed proof of a hardware fault.

---

## Overview

- Runs as a Windows service (`PCDiagnosticAgent`, auto-start, LocalSystem) — no
  login required, no console window.
- Collects metrics on a schedule (CPU, RAM, disk, top processes, uptime, GPU,
  temperatures) and tails the Windows System Event Log incrementally.
- Records a heartbeat and persistent sessions per boot so a reboot is detected
  the moment the service starts again.
- Runs the diagnostic engine on startup to classify how the **previous session**
  ended: normal restart, hard hang, power loss, BSOD, or unexpected shutdown.
- Preserves the diagnostic evidence window around an incident from routine
  retention cleanup.
- Generates an HTML diagnostic report and an optional ZIP export bundle.
- Includes a **safe, isolated simulation harness** to exercise the diagnostic
  pipeline with synthetic data — no real reboot or crash required.

## Features

- Auto-start Windows service (pywin32) with watchdog + heartbeat.
- Isolated collectors: a failing collector never stops the agent.
- SQLite storage (WAL mode) with rolling retention and incident-window protection.
- Incremental System Event Log tailing with a persisted record cursor (no
  full-log rescans; tolerates cleared logs).
- Boot/session detection that reuses the session on a plain service restart.
- Rule-based incident classification (no LLM, no cloud).
- Evidence-driven findings with severity + confidence (LOW/MEDIUM/HIGH).
- Technician CLI (`pcdiag`) for health, status, events, diagnostics, reports and
  export.
- Safe simulation harness (`pcdiag simulate-incident`) for hard-hang, power-loss,
  BSOD and normal-restart scenarios using isolated synthetic data.

## How It Works

1. **Collect** — a scheduler runs high-frequency collectors every 30 s (default)
   and low-frequency collectors every 5 minutes (default). Each snapshot is
   written to a local SQLite database.
2. **Tail** — the Event Log collector reads only the newest System-log records
   since the last processed record id, so it never re-reads history.
3. **Detect boot** — on every start, the agent records a new session. If the OS
   boot time is the same as the latest session's boot time, it is a service
   restart and the existing session is reused (no duplicate sessions).
4. **Analyse** — after a reboot, the diagnostic engine correlates the previous
   session's events, metrics, heartbeats and boot signals to classify how it ended.
5. **Report** — a technician can generate an HTML report or export a ZIP bundle
   containing the report, database, events, logs and system info.

```
┌──────────────────────────────────────────────────────────────┐
│  Scheduler ──► Collectors (CPU, RAM, disk, proc, events, …) │
│       │                                                      │
│       ▼                                                      │
│  SQLite (WAL)  ◄── heartbeat + watchdog                      │
│       │                                                      │
│       ▼                                                      │
│  On restart: detect_boot ─► run_diagnosis ─► incident/findings│
│       │                                                      │
│       ▼                                                      │
│  pcdiag report ──► HTML report   ·   pcdiag export ──► ZIP   │
└──────────────────────────────────────────────────────────────┘
```

## Incident Classification

On startup after a reboot, the engine examines the previous session and classifies
its termination. Signals are combined into a **probable termination mode** with a
confidence level:

- **CLEAN / NORMAL RESTART** — no incident.
  Evidence: `User32 1074` (user/process initiated shutdown) and/or `EventLog 6006`
  (Event Log service stopped cleanly); **no** Kernel-Power 41, **no** Event 6008,
  **no** BugCheck 1001.

- **HARD HANG** — the machine froze and was force-restarted.
  Evidence: Kernel-Power 41 present, no clean-shutdown event, no BugCheck, and
  diagnostic activity (metrics/heartbeat) stops some time **before** the reboot.
  Hard-hang threshold (as implemented in `diagnostics/hang_detector.py`, with the
  default 30 s collection interval):
  - gap ≥ 5 × interval (150 s) → **HIGH** confidence hard hang
  - gap ≥ 2 × interval (60 s) → **MEDIUM** confidence hard hang
  - no metrics at all → **LOW** confidence hard hang

- **POWER LOSS** — an abrupt cut, not a freeze.
  Evidence: Kernel-Power 41 present, no clean shutdown, no BugCheck, and activity
  stops essentially at reboot time (gap < 2 × interval, i.e. < 60 s) → **LOW**
  confidence. Kernel-Power 41 alone is treated as "an ungraceful shutdown
  occurred", **not** proof of a PSU fault.

- **BSOD / BugCheck** — a blue screen.
  Evidence: `BugCheck 1001` (e.g. from `BugCheck` or WER providers) → **HIGH**
  confidence, independent of the metric gap.

- **UNEXPECTED REBOOT** — an unclean transition not explained by a hang or BSOD.
  Event 6008 (`EventLog`) is treated as an unexpected-shutdown signal; combined
  with a non-clean session and Kernel-Power 41, the session is flagged as ending
  unexpectedly.

- **UNKNOWN** — insufficient evidence for a stronger inference.

### Supported incident types (as emitted by the engine)

`HARD_HANG`, `BSOD`, `POWER_LOSS`, `UNEXPECTED_REBOOT`, `UNKNOWN`.

### Evidence vs Inference

- **FACT / EVIDENCE** — what was actually observed: event IDs present, metric
  maxima, heartbeat timestamps, the boot gap.
- **SESSION ANALYSIS** — session-level state derived by the engine (e.g. "previous
  session ended cleanly: NO").
- **INFERENCE / HYPOTHESIS** — the engine's interpretation (e.g. "possible hard
  hang, HIGH confidence"). This is a hypothesis based on available evidence, never
  a guarantee of a specific hardware cause.

The report generator and simulation output label these explicitly.

## False-Positive Protection

The following reliability protections are implemented in `diagnostics/`:

- **Event ID normalization.** Windows Event IDs read through the classic Event Log
  API can have the high bit set (stored as signed integers). IDs are normalized
  with `& 0xFFFF` before any comparison, so event matching is correct regardless
  of storage format.
- **Kernel-Power requires Event 41.** Only events whose actual ID is `41` on a
  Kernel-Power provider are treated as a power-loss signal. Routine Kernel-Power
  events (109/172/521, logged at every boot) are ignored.
- **Disk errors require provider + ID.** A storage error is counted only when the
  provider is a storage provider (Disk, NTFS, StorPort, …) **and** the event ID is
  in the known disk-error set. Event ID alone is never sufficient.
- **Evidence scoped to the incident window.** Event/metric evidence used for a
  finding is limited to the configured window around the reboot (default 30
  minutes before, 5 minutes after), so historical events from the whole previous
  session cannot inflate a finding.
- **No duplicate sessions on service restart.** If the OS boot time matches the
  latest session's boot time, the service restart reuses that session instead of
  creating a new one — preventing spurious incidents and bogus "previous session"
  analysis.

## Installation

### Build machine (optional — only needed to produce the executable)

- Windows 10/11, Python 3.12+ (64-bit).
- `build.ps1` runs the test suite and produces `dist\pcdiag\pcdiag.exe` with
  PyInstaller (bundles `config.yaml`).

### Target machine (no Python required)

The service is packaged as a standalone executable. On the target machine, from an
**elevated** PowerShell prompt in the package folder:

```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1
```

`install.ps1`:

1. Creates `C:\ProgramData\PCDiagnosticAgent\{bin,data,logs,reports}`.
2. Copies `dist\pcdiag\*` to `...\bin`.
3. Installs the auto-start Windows service `PCDiagnosticAgent` (LocalSystem).
4. Starts the service and runs a status + health check.

Verify the installation:

```powershell
Get-Service PCDiagnosticAgent
& "C:\ProgramData\PCDiagnosticAgent\bin\pcdiag.exe" health
```

Uninstall (elevated):

```powershell
powershell -ExecutionPolicy Bypass -File .\uninstall.ps1            # keep data
powershell -ExecutionPolicy Bypass -File .\uninstall.ps1 -PurgeData  # delete everything
```

## Usage

Copy-paste ready PowerShell examples (using the installed executable):

```powershell
$exe = "C:\ProgramData\PCDiagnosticAgent\bin\pcdiag.exe"

# Quick health check (database + heartbeat freshness)
& $exe health

# Agent / data / service status
& $exe status

# Recent Windows System events (last 20)
& $exe events --limit 20

# Analyse the previous session
& $exe diagnostics

# Generate the HTML report
& $exe report

# List recorded incidents
& $exe incidents

# Export a diagnostic bundle (report + DB + events + logs + system info)
& $exe export
```

## CLI Commands

| Command | Description |
|---|---|
| `pcdiag status` | Agent, data directory, heartbeat, current boot, latest incident |
| `pcdiag info` | System information (CPU, RAM, disk, GPU, uptime, boot) |
| `pcdiag health` | Database + heartbeat health check |
| `pcdiag events [--limit N] [--verbose]` | Recent Windows System events |
| `pcdiag incidents [--limit N]` | List recorded incidents |
| `pcdiag diagnostics` | Analyse the previous session (technician view) |
| `pcdiag report [--incident ID]` | Generate the HTML diagnostic report |
| `pcdiag simulate-incident --type <type>` | Run the safe simulation harness |
| `pcdiag export [--output DIR]` | Export a diagnostic ZIP bundle |
| `pcdiag service install\|remove\|start\|stop\|restart` | Manage the Windows service |

### Simulation / Test Harness

`pcdiag simulate-incident` runs the **real** diagnostic engine against a fully
synthetic, deterministic previous session. It never reads the live Windows Event
Log and never touches the production database.

```powershell
pcdiag simulate-incident --type hard-hang
pcdiag simulate-incident --type power-loss
pcdiag simulate-incident --type bsod
pcdiag simulate-incident --type normal-restart
```

- The harness writes its own SQLite database under the isolated simulation
  workspace (default `C:\ProgramData\PCDiagnosticAgent\test-data`, override with
  `--workspace`). The production database
  (`C:\ProgramData\PCDiagnosticAgent\data\agent.db`) is never opened or modified.
- Each scenario seeds a previous session (boot time, metrics every 30 s,
  heartbeats, and the relevant Windows events), then runs `detect_boot` +
  `run_diagnosis` and generates an HTML report labelled **SIMULATION / TEST DATA**.
- Expected outcomes: `hard-hang` → HARD_HANG / HIGH, `power-loss` → POWER_LOSS /
  LOW, `bsod` → BSOD / HIGH, `normal-restart` → NO incident.

## Diagnostic Reports

```powershell
pcdiag report
```

writes

```
C:\ProgramData\PCDiagnosticAgent\reports\report.html
```

A self-contained HTML file viewable in any browser. Structure:

- **FACT** / **EVIDENCE** / **SESSION ANALYSIS** / **INFERENCE** / **HYPOTHESIS**
  — explicit evidence-vs-inference blocks (added by the simulation harness; the
  whole report is clearly labelled as synthetic test data).
- **Incident Summary** — incident type, confidence, detected at, last activity,
  estimated hang duration.
- **Timeline** — events and metric samples in the incident window.
- **Previous Session** — previous boot, cleanly/expectedly-ended state, Kernel-Power
  41, BugCheck, uptime.
- **Findings** — each finding with severity, confidence, evidence and explanation.
- **Possible Causes** — hypothesis hints only.
- **Recommended Next Steps** — suggested technician actions.

Diagnostic conclusions in reports are **hypotheses based on available evidence**
and are not guaranteed proof of hardware failure.

## Development

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pytest -q
```

Run the agent in the foreground (debugging only), isolated from real data:

```powershell
$env:PCDIAG_HOME = "$env:TEMP\pcdiag-dev"
.\.venv\Scripts\python.exe -m agent.main
```

`PCDIAG_HOME` overrides the data directory (default `C:\ProgramData\PCDiagnosticAgent`)
so development never touches real data.

## Testing

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Current suite: **80 passed**. Coverage includes:

- Configuration validation and defaults.
- Storage, migrations, retention, event/incident persistence.
- Event classification (Kernel-Power 41 gating, disk provider+ID, ID masking).
- Boot detection (clean/unexpected shutdown, service-restart session reuse).
- Hang/crash inference (thresholds, confidence levels).
- End-to-end incident classification (BSOD, hard hang, power loss, normal restart).
- Regression tests for the false-positive protections above.
- Report generation and terminology consistency.
- Simulation harness: 4 scenarios, isolation from the production database,
  determinism.

Validation status (supported by the repository's test suite and `simulation/`):

- Full test suite: **80 passed**
- HARD_HANG classification: **PASS**
- Report terminology: **PASS**
- Production database untouched during simulation validation: **YES**

## Project Structure

```
pc-diagnostic-agent/
├── agent/                 # config, scheduler, lifecycle, foreground entry
├── cli/                   # technician CLI (argparse)
├── collectors/            # isolated metric + event collectors
├── common/                # paths, logging, system info, time utilities
├── diagnostics/           # boot detection, crash/hang inference, rule engine
├── reports/               # HTML report generator + template
│   └── templates/         #   report.html
├── service/               # pywin32 Windows service wrapper
├── simulation/            # safe synthetic-data harness (scenarios + runner)
├── storage/               # SQLite (WAL), schema/migrations, retention
├── watchdog/              # heartbeat + watchdog thread
├── tests/                 # pytest suite (mock scenario builders)
├── docs/                  # troubleshooting guide, example report
├── config.yaml            # validated configuration
├── requirements.txt
├── build.ps1              # run tests + build executable
├── install.ps1            # install service (elevated)
├── uninstall.ps1          # remove service (elevated)
└── pcdiag.py              # unified entry point (CLI + service dispatcher)
```

## Safety and Privacy

- **Local only.** No outbound network connections, no telemetry, no cloud, no
  analytics. The only "network" call is reading the local host name.
- **No sensitive data.** Never collects browser history, keystrokes, screenshots,
  mic/webcam, personal files, or credentials. Process command lines (which may
  contain secrets) are deliberately **not** captured.
- **No kernel drivers**, no destructive SMART/repair commands.
- **Isolated collectors.** One failing collector never stops the agent.
- **Simulation is isolated.** `simulate-incident` writes only to its own
  `test-data` workspace and never modifies the production database.

## Limitations

- A **hard hang cannot be self-observed** by the frozen machine; it is inferred
  post-reboot from the last heartbeat/metric timestamp, the absence of a
  clean-shutdown event, Kernel-Power 41, and the absence of a BugCheck.
- **GPU / temperature** data is best-effort (depends on `nvidia-smi` / WMI);
  otherwise reported as unavailable.
- The **Event Log collector** ingests at most the newest 1,000 System events per
  run; older history is not back-filled.
- **Event record ids** are per-channel and can reset when a log is cleared; the
  collector detects this and re-syncs by timestamp.
- The **classic Event Log API** does not expose process/thread ids for these
  records (stored as `NULL`).
- The **watchdog** lives in the same process; it can recover a crashed scheduler
  thread but not a whole-kernel freeze (handled post-reboot).
- **Diagnosis is inference, not certainty.** Termination mode is reported with
  LOW/MEDIUM/HIGH confidence only.

## Troubleshooting

See [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) for service startup issues,
stale heartbeats, missing incidents, GPU/temperature unavailability, corrupted
databases, and clean uninstall steps.

## Contributing

This is a small, focused, local-only diagnostic tool. Contributions that keep it
local, safe and deterministic are welcome. Please:

1. Open an issue to discuss the change first.
2. Add or update tests for any behavior change (see `tests/`).
3. Run the full suite: `.\.venv\Scripts\python.exe -m pytest -q`.
4. Do not add cloud, networking, telemetry, remote control, or AI/LLM features
   unless explicitly requested and approved.

## License

No license is currently specified for this repository.
