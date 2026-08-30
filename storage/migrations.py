"""SQLite schema definitions and index creation.

The schema is kept deliberately simple and append-only for hot paths so writes
stay fast and resilient to sudden power loss (WAL mode + short transactions).
"""

from __future__ import annotations

# Maps a metric table name to its columns.  Every metric table additionally
# carries an auto ``id`` primary key, a ``timestamp`` (real) and a
# ``session_id`` (integer) which are injected by the storage layer.
METRIC_TABLES: dict[str, list[str]] = {
    "metrics_cpu": ["cpu_percent", "cpu_frequency", "processor_count"],
    "metrics_memory": [
        "memory_total",
        "memory_used",
        "memory_available",
        "memory_percent",
        "swap_percent",
    ],
    "metrics_disk": [
        "device",
        "mountpoint",
        "total",
        "used",
        "free",
        "percent",
        "read_bytes",
        "write_bytes",
        "read_latency_ms",
        "write_latency_ms",
        "disk_model",
        "disk_type",
    ],
    "metrics_gpu": [
        "gpu_name",
        "utilization",
        "memory_used",
        "memory_total",
        "temperature_c",
        "driver_version",
    ],
    "metrics_temperature": ["sensor", "temperature_c"],
    "metrics_process": [
        "pid",
        "name",
        "cpu_percent",
        "memory_bytes",
        "exe_path",
    ],
    "metrics_uptime": ["boot_time", "uptime_seconds"],
}

SCHEMA_STATEMENTS: list[str] = [
    "CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)",
    """
    CREATE TABLE IF NOT EXISTS sessions (
        session_id INTEGER PRIMARY KEY AUTOINCREMENT,
        boot_time REAL NOT NULL,
        previous_boot_time REAL,
        uptime_before_boot REAL,
        previous_session_clean INTEGER,
        unexpected_shutdown INTEGER,
        kernel_power_detected INTEGER,
        bugcheck_detected INTEGER,
        created_at REAL NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp REAL NOT NULL,
        session_id INTEGER,
        provider TEXT,
        event_id INTEGER,
        level INTEGER,
        channel TEXT,
        record_id INTEGER,
        message TEXT,
        computer TEXT,
        process_id INTEGER,
        thread_id INTEGER
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS incidents (
        incident_id INTEGER PRIMARY KEY AUTOINCREMENT,
        detected_at REAL NOT NULL,
        incident_type TEXT,
        confidence TEXT,
        previous_session_id INTEGER,
        last_metric_timestamp REAL,
        reboot_timestamp REAL,
        duration_estimate REAL,
        findings TEXT,
        evidence TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS findings (
        finding_id INTEGER PRIMARY KEY AUTOINCREMENT,
        incident_id INTEGER,
        finding_type TEXT,
        severity TEXT,
        confidence TEXT,
        evidence TEXT,
        timestamp REAL,
        explanation TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS heartbeat (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        timestamp REAL NOT NULL,
        updated_at REAL NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS agent_state (
        key TEXT PRIMARY KEY,
        value TEXT,
        updated_at REAL NOT NULL
    )
    """,
]

INDEX_STATEMENTS: list[str] = [
    "CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp)",
    "CREATE INDEX IF NOT EXISTS idx_events_event_id ON events(event_id)",
    "CREATE INDEX IF NOT EXISTS idx_events_provider ON events(provider)",
    "CREATE INDEX IF NOT EXISTS idx_events_session ON events(session_id)",
    "CREATE INDEX IF NOT EXISTS idx_sessions_boot ON sessions(boot_time)",
    "CREATE INDEX IF NOT EXISTS idx_incidents_detected ON incidents(detected_at)",
]

SCHEMA_VERSION = 1


def _metric_table_ddl() -> list[str]:
    statements: list[str] = []
    for table, columns in METRIC_TABLES.items():
        cols = [
            "id INTEGER PRIMARY KEY AUTOINCREMENT",
            "timestamp REAL NOT NULL",
            "session_id INTEGER",
        ] + list(columns)
        statements.append(
            f"CREATE TABLE IF NOT EXISTS {table} ({', '.join(cols)})"
        )
    return statements


# Emit the metric table DDL so the storage layer always has the full schema.
SCHEMA_STATEMENTS.extend(_metric_table_ddl())


def metric_columns(table: str) -> list[str]:
    if table not in METRIC_TABLES:
        raise KeyError(f"unknown metric table: {table}")
    return list(METRIC_TABLES[table])
