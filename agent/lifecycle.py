"""Agent lifecycle orchestration.

Ties together boot detection, initial event collection, incident detection,
report generation, the scheduler and the watchdog.  The service and the
foreground entry point both drive this class.
"""

from __future__ import annotations

import logging
import threading
import time

from agent.config import Config, load_config
from agent.scheduler import Scheduler
from collectors import base as collector_base
from collectors.windows_events import WindowsEventCollector
from common import logging_setup, paths
from diagnostics import boot_detector, diagnosis
from reports import report_generator
from storage.database import Database
from watchdog.watchdog import Watchdog

logger = logging.getLogger(__name__)


class Agent:
    def __init__(self, config: Config | None = None, db_path: str | None = None):
        self.config = config or load_config()
        self.db = Database(db_path or paths.database_path())
        self.scheduler = Scheduler(self.db, self.config)
        self.session_id: int | None = None
        self._worker_stop = threading.Event()
        self._worker: threading.Thread | None = None

    def initialize(self) -> None:
        paths.ensure_directories()
        logging_setup.configure_logging(self.config.logging_level)
        self.db.connect()

    def startup_analysis(self) -> tuple[dict, dict]:
        now = time.time()
        boot = boot_detector.detect_boot(self.db, now)
        self.session_id = boot["session_id"]

        # Collect events immediately so boot-time crash events (Kernel-Power 41,
        # BugCheck 1001, 6008) are available for the diagnostic engine.
        event_collector = WindowsEventCollector("System")
        collector_base.run_isolated(event_collector.collect, now, self.session_id, self.db)

        result = diagnosis.run_diagnosis(self.db, boot, self.config)
        if result.get("incident"):
            try:
                report_generator.generate_report(
                    self.db, self.config, result["incident"]["incident_id"]
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("report generation failed: %s", exc)
        return boot, result

    def session_provider(self) -> int:
        return self.session_id if self.session_id is not None else 1

    def _start_worker(self) -> threading.Thread:
        self._worker_stop.clear()
        thread = threading.Thread(
            target=self.scheduler.loop,
            args=(self._worker_stop, self.session_provider),
            name="scheduler",
            daemon=True,
        )
        thread.start()
        return thread

    def _restart_worker(self) -> None:
        self._worker_stop.set()
        if self._worker is not None and self._worker.is_alive():
            self._worker.join(timeout=10.0)
        self._worker = self._start_worker()
        logger.info("scheduler restarted by watchdog")

    def run(self, stop_event: threading.Event) -> None:
        self._worker = self._start_worker()
        watchdog = Watchdog(self.db, on_restart=self._restart_worker)
        watchdog.start()
        try:
            while not stop_event.is_set():
                stop_event.wait(1.0)
        finally:
            self._worker_stop.set()
            watchdog.stop()
            watchdog.join(timeout=5.0)
            if self._worker is not None:
                self._worker.join(timeout=5.0)
            self.db.close()
