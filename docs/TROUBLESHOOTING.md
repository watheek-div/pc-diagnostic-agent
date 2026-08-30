# Troubleshooting

## Service won't start

1. Check the Windows Application event log for entries from `PCDiagnosticAgent`.
2. Check the agent log: `C:\ProgramData\PCDiagnosticAgent\logs\agent.log`.
3. Confirm the database directory is writable by LocalSystem:
   `C:\ProgramData\PCDiagnosticAgent\data`.
4. Run a health check: `pcdiag health`.
5. Start the service manually and read the error:

   ```powershell
   pcdiag service start
   Get-Service PCDiagnosticAgent
   ```

## No incidents are being detected

- The agent must be running *across* a reboot to detect the previous session's
  shutdown state. It cannot reconstruct metrics it never collected.
- Verify the heartbeat is fresh: `pcdiag status`.
- Verify events are being collected: `pcdiag events --limit 20`.

## Heartbeat is stale / watchdog keeps restarting the scheduler

- Look at `agent.log` for a repeating collector error. A collector failing
  repeatedly is isolated, but a fault in the scheduler loop itself will be
  logged and restarted by the watchdog (with backoff).
- If the whole machine froze, the heartbeat will be stale until the next boot
  — this is expected and is exactly what post-reboot detection analyses.

## "GPU / temperature: unavailable"

This is normal on hardware without `nvidia-smi` (AMD/Intel or missing NVIDIA
drivers). The agent degrades gracefully; it does not indicate a fault.

## Report is missing data

- Retention (default 24 h) prunes old metrics, but the incident window is
  preserved. Older non-incident history is intentionally discarded.
- If the previous boot predates agent installation, there is no metric history
  for it (only Event Log evidence is available).

## Recovering a corrupted database

The database is SQLite with WAL mode. If `pcdiag status` reports a database
error:

1. Stop the service: `pcdiag service stop`.
2. Back up `agent.db`, `agent.db-wal`, `agent.db-shm`.
3. Run `sqlite3 agent.db "PRAGMA integrity_check;"` (sqlite3 CLI) or simply
   move the files aside and restart the service to recreate an empty database.

## Uninstalling cleanly

```powershell
.\uninstall.ps1 -PurgeData
```

## Network activity

The agent makes **no outbound connections**. If you observe any network
activity from `pcdiag.exe`, report it — it is not expected behaviour.
