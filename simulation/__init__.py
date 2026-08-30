"""Safe diagnostic simulation harness.

Builds fully synthetic, internally-consistent incident data in an isolated
SQLite database and runs the real diagnostic engine against it.  It never
touches the live production database, never reads the live Windows Event Log,
and never causes any real OS-side effect (no BSOD, no reboot, no forced
shutdown, no CPU/RAM/disk exhaustion, no driver faults).
"""