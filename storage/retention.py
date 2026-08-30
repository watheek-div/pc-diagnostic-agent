"""Rolling retention.

Old metrics are pruned to keep the database bounded, but evidence immediately
around a detected incident is preserved.  Incidents and their associated
findings/sessions are never deleted by routine retention.
"""

from __future__ import annotations

import time

from storage import migrations
from storage.database import Database


def prune_metrics(db: Database, retention_hours: float) -> dict:
    """Delete metrics older than ``retention_hours``.

    Rows that fall inside a protected incident window (any incident's
    ``last_metric_timestamp`` minus ``before`` margin through its reboot plus
    ``after`` margin) are retained.
    """
    if retention_hours <= 0:
        return {"deleted": 0}

    cutoff = time.time() - retention_hours * 3600.0
    protected: list[tuple[float, float]] = []
    try:
        incidents = db.list_incidents(limit=200)
        for inc in incidents:
            last = inc["last_metric_timestamp"]
            reboot = inc["reboot_timestamp"]
            if last and reboot:
                protected.append((last - 3600.0, reboot + 600.0))
    except Exception:
        protected = []

    total_deleted = 0
    for table in migrations.METRIC_TABLES:
        where = "timestamp < ?"
        params: list = [cutoff]
        for start, end in protected:
            where += " AND NOT (timestamp >= ? AND timestamp <= ?)"
            params.extend([start, end])
        try:
            rows = db.query(f"SELECT COUNT(*) AS n FROM {table} WHERE {where}", tuple(params))
            to_delete = rows[0]["n"] if rows else 0
            if to_delete:
                db.execute(f"DELETE FROM {table} WHERE {where}", tuple(params))
                total_deleted += to_delete
        except Exception:
            continue

    return {"deleted_rows": total_deleted}
