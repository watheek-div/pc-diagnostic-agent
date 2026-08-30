"""Collection scheduler.

Separates high-frequency collectors (every ``collection_interval_seconds``)
from low-frequency collectors (every ``low_frequency_interval_seconds``) so the
agent stays lightweight.  Every collector is isolated: one failure never stops
the loop.
"""

from __future__ import annotations

import logging
import time

from collectors import base as collector_base
from collectors.cpu import CpuCollector
from collectors.disk import DiskCollector
from collectors.gpu import GpuCollector
from collectors.memory import MemoryCollector
from collectors.processes import ProcessCollector
from collectors.temperature import TemperatureCollector
from collectors.uptime import UptimeCollector
from collectors.windows_events import WindowsEventCollector
from storage import retention

logger = logging.getLogger(__name__)


class Scheduler:
    def __init__(self, db, config):
        self.db = db
        self.config = config
        self.high_frequency = [
            CpuCollector(),
            MemoryCollector(),
            DiskCollector(),
            ProcessCollector(),
            UptimeCollector(),
        ]
        self.low_frequency = [
            GpuCollector(),
            TemperatureCollector(),
            WindowsEventCollector("System"),
        ]
        self._last_retention = 0.0

    def collect_high(self, now: float, session_id: int) -> int:
        snapshot: dict = {}
        for collector in self.high_frequency:
            result = collector_base.run_isolated(collector.collect, now, session_id)
            if result:
                snapshot.update(result)
        inserted = self.db.insert_snapshot(snapshot, now, session_id)
        self.db.update_heartbeat(now)
        try:
            from common import paths
            from watchdog import heartbeat as hb

            hb.write_heartbeat_file(paths.heartbeat_file_path(), now)
        except Exception:  # noqa: BLE001
            pass
        return inserted

    def collect_low(self, now: float, session_id: int) -> None:
        snapshot: dict = {}
        for collector in self.low_frequency:
            result = collector_base.run_isolated(collector.collect, now, session_id, self.db)
            if result:
                snapshot.update(result)
        if snapshot:
            self.db.insert_snapshot(snapshot, now, session_id)
        # Opportunistic retention during the low-frequency cycle.
        if now - self._last_retention >= max(300, self.config.low_frequency_interval_seconds):
            try:
                retention.prune_metrics(self.db, self.config.retention_hours)
            except Exception as exc:  # noqa: BLE001
                logger.warning("retention failed: %s", exc)
            self._last_retention = now

    def loop(self, stop_event, session_provider) -> None:
        last_high = 0.0
        last_low = 0.0
        high_interval = self.config.collection_interval_seconds
        low_interval = self.config.low_frequency_interval_seconds

        while not stop_event.is_set():
            now = time.time()
            session_id = session_provider()

            if now - last_high >= high_interval:
                try:
                    self.collect_high(now, session_id)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("high-frequency cycle failed: %s", exc)
                last_high = now

            if now - last_low >= low_interval:
                try:
                    self.collect_low(now, session_id)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("low-frequency cycle failed: %s", exc)
                last_low = now

            stop_event.wait(1.0)
