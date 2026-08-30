"""SQLite-backed storage.

Design notes
------------
* WAL journal mode + ``synchronous=NORMAL`` give good crash resilience with
  acceptable write throughput for a low-frequency diagnostic collector.
* A single connection is guarded by a ``threading.RLock`` so the scheduler
  thread, watchdog thread and CLI can share it safely.
* Metrics are written in short transactions per snapshot so a power loss never
  leaves the database in a corrupt state.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading

from storage import migrations

_SAFE_METRIC_TABLES = set(migrations.METRIC_TABLES.keys())


class Database:
    def __init__(self, path: str):
        self.path = path
        self._lock = threading.RLock()
        self._conn: sqlite3.Connection | None = None

    # -- lifecycle ---------------------------------------------------------
    def connect(self) -> None:
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
        self._apply_migrations()

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    def _apply_migrations(self) -> None:
        with self._lock:
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)"
            )
            cur = self._conn.execute(
                "SELECT version FROM schema_version ORDER BY version DESC LIMIT 1"
            )
            row = cur.fetchone()
            current = row["version"] if row else 0
            if current >= migrations.SCHEMA_VERSION:
                return
            for statement in migrations.SCHEMA_STATEMENTS:
                self._conn.execute(statement)
            for statement in migrations.INDEX_STATEMENTS:
                self._conn.execute(statement)
            self._conn.execute(
                "INSERT OR REPLACE INTO schema_version (version) VALUES (?)",
                (migrations.SCHEMA_VERSION,),
            )
            self._conn.commit()

    # -- metrics -----------------------------------------------------------
    def insert_snapshot(self, snapshot: dict, timestamp: float, session_id: int) -> int:
        """Persist a collection snapshot.

        ``snapshot`` maps a metric table name to a list of row dicts.  Unknown
        tables/columns are ignored so a buggy collector cannot corrupt storage.
        """
        count = 0
        with self._lock:
            for table, rows in snapshot.items():
                if table not in _SAFE_METRIC_TABLES or not rows:
                    continue
                columns = migrations.metric_columns(table)
                col_names = ["timestamp", "session_id"] + columns
                placeholders = ", ".join(["?"] * len(col_names))
                sql = (
                    f"INSERT INTO {table} ({', '.join(col_names)}) "
                    f"VALUES ({placeholders})"
                )
                for row in rows:
                    values = [timestamp, session_id]
                    for col in columns:
                        values.append(row.get(col))
                    try:
                        self._conn.execute(sql, values)
                        count += 1
                    except sqlite3.Error:
                        continue
            self._conn.commit()
        return count

    def insert_events(self, rows: list[dict], session_id: int) -> int:
        columns = [
            "timestamp", "session_id", "provider", "event_id", "level",
            "channel", "record_id", "message", "computer", "process_id",
            "thread_id",
        ]
        placeholders = ", ".join(["?"] * len(columns))
        sql = (
            f"INSERT INTO events ({', '.join(columns)}) VALUES ({placeholders})"
        )
        count = 0
        with self._lock:
            for row in rows:
                values = [
                    row.get("timestamp"),
                    session_id,
                    row.get("provider"),
                    row.get("event_id"),
                    row.get("level"),
                    row.get("channel"),
                    row.get("record_id"),
                    _clip(row.get("message"), 4000),
                    row.get("computer"),
                    row.get("process_id"),
                    row.get("thread_id"),
                ]
                try:
                    self._conn.execute(sql, values)
                    count += 1
                except sqlite3.Error:
                    continue
            self._conn.commit()
        return count

    # -- sessions ----------------------------------------------------------
    def create_session(self, boot_time: float, created_at: float) -> int:
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO sessions (boot_time, created_at) VALUES (?, ?)",
                (boot_time, created_at),
            )
            self._conn.commit()
            return cur.lastrowid

    def update_session(self, session_id: int, **fields) -> None:
        if not fields:
            return
        allowed = {
            "previous_boot_time", "uptime_before_boot", "previous_session_clean",
            "unexpected_shutdown", "kernel_power_detected", "bugcheck_detected",
        }
        sets = []
        values = []
        for key, value in fields.items():
            if key in allowed:
                sets.append(f"{key} = ?")
                values.append(value)
        if not sets:
            return
        values.append(session_id)
        with self._lock:
            self._conn.execute(
                f"UPDATE sessions SET {', '.join(sets)} WHERE session_id = ?",
                values,
            )
            self._conn.commit()

    def latest_session(self) -> sqlite3.Row | None:
        with self._lock:
            cur = self._conn.execute(
                "SELECT * FROM sessions ORDER BY session_id DESC LIMIT 1"
            )
            return cur.fetchone()

    def get_session(self, session_id: int) -> sqlite3.Row | None:
        with self._lock:
            cur = self._conn.execute(
                "SELECT * FROM sessions WHERE session_id = ?", (session_id,)
            )
            return cur.fetchone()

    # -- incidents ---------------------------------------------------------
    def create_incident(self, incident: dict, findings: list[dict]) -> int:
        with self._lock:
            cur = self._conn.execute(
                """
                INSERT INTO incidents (
                    detected_at, incident_type, confidence, previous_session_id,
                    last_metric_timestamp, reboot_timestamp, duration_estimate,
                    findings, evidence
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    incident.get("detected_at"),
                    incident.get("incident_type"),
                    incident.get("confidence"),
                    incident.get("previous_session_id"),
                    incident.get("last_metric_timestamp"),
                    incident.get("reboot_timestamp"),
                    incident.get("duration_estimate"),
                    json.dumps(incident.get("findings", [])),
                    json.dumps(incident.get("evidence", [])),
                ),
            )
            incident_id = cur.lastrowid
            for finding in findings:
                self._conn.execute(
                    """
                    INSERT INTO findings (
                        incident_id, finding_type, severity, confidence,
                        evidence, timestamp, explanation
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        incident_id,
                        finding.get("type"),
                        finding.get("severity"),
                        finding.get("confidence"),
                        json.dumps(finding.get("evidence", [])),
                        finding.get("timestamp"),
                        finding.get("explanation"),
                    ),
                )
            self._conn.commit()
            return incident_id

    def list_incidents(self, limit: int = 20) -> list[sqlite3.Row]:
        with self._lock:
            cur = self._conn.execute(
                "SELECT * FROM incidents ORDER BY incident_id DESC LIMIT ?", (limit,)
            )
            return cur.fetchall()

    def get_incident(self, incident_id: int) -> sqlite3.Row | None:
        with self._lock:
            cur = self._conn.execute(
                "SELECT * FROM incidents WHERE incident_id = ?", (incident_id,)
            )
            return cur.fetchone()

    def list_findings(self, incident_id: int) -> list[sqlite3.Row]:
        with self._lock:
            cur = self._conn.execute(
                "SELECT * FROM findings WHERE incident_id = ? ORDER BY finding_id",
                (incident_id,),
            )
            return cur.fetchall()

    # -- heartbeat / state -------------------------------------------------
    def update_heartbeat(self, timestamp: float) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO heartbeat (id, timestamp, updated_at) VALUES (1, ?, ?)
                ON CONFLICT(id) DO UPDATE SET timestamp = excluded.timestamp,
                                              updated_at = excluded.updated_at
                """,
                (timestamp, timestamp),
            )
            self._conn.commit()

    def get_heartbeat(self) -> float | None:
        with self._lock:
            cur = self._conn.execute("SELECT timestamp FROM heartbeat WHERE id = 1")
            row = cur.fetchone()
            return row["timestamp"] if row else None

    def set_state(self, key: str, value: str) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO agent_state (key, value, updated_at) VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value,
                                              updated_at = excluded.updated_at
                """,
                (key, value, _now_epoch()),
            )
            self._conn.commit()

    def get_state(self, key: str) -> str | None:
        with self._lock:
            cur = self._conn.execute(
                "SELECT value FROM agent_state WHERE key = ?", (key,)
            )
            row = cur.fetchone()
            return row["value"] if row else None

    # -- queries -----------------------------------------------------------
    def query(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        with self._lock:
            cur = self._conn.execute(sql, params)
            return cur.fetchall()

    def execute(self, sql: str, params: tuple = ()) -> None:
        with self._lock:
            self._conn.execute(sql, params)
            self._conn.commit()

    def vacuum(self) -> None:
        with self._lock:
            self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")


def _clip(value: str | None, limit: int) -> str | None:
    if value is None:
        return None
    value = str(value)
    return value[:limit]


def _now_epoch() -> float:
    import time

    return time.time()
