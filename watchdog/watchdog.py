"""Lightweight watchdog.

Runs in its own thread and checks whether the scheduler is still updating the
heartbeat.  If the heartbeat goes stale (e.g. the scheduler thread died on an
unhandled error) it records the failure and asks the manager to restart the
worker, with backoff so it never spins on a permanently broken component.

Known limitation (documented): because the watchdog lives in the same process
as the agent, it cannot detect or recover from a *whole-kernel* freeze — that is
expected and is handled by post-reboot detection instead.
"""

from __future__ import annotations

import logging
import threading
import time

logger = logging.getLogger(__name__)


class Watchdog(threading.Thread):
    def __init__(
        self,
        db,
        on_restart,
        check_interval: float = 10.0,
        stale_after: float = 90.0,
        max_restarts: int = 5,
        backoff_seconds: float = 60.0,
    ):
        super().__init__(name="watchdog", daemon=True)
        self.db = db
        self.on_restart = on_restart
        self.check_interval = check_interval
        self.stale_after = stale_after
        self.max_restarts = max_restarts
        self.backoff_seconds = backoff_seconds
        self._stop_event = threading.Event()
        self._restarts = 0
        self._last_restart = 0.0
        self.stale_detected = threading.Event()

    def stop(self) -> None:
        self._stop_event.set()

    def run(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._check()
            except Exception as exc:  # noqa: BLE001
                logger.warning("watchdog check failed: %s", exc)
            self._stop_event.wait(self.check_interval)

    def _check(self) -> None:
        heartbeat = self.db.get_heartbeat()
        if heartbeat is None:
            # No heartbeat yet: agent may still be starting up.
            return
        now = time.time()
        if now - heartbeat > self.stale_after:
            self.stale_detected.set()
            logger.error(
                "heartbeat stale for %.0fs", now - heartbeat
            )
            self._record_failure(now)
            if self._restarts < self.max_restarts and now - self._last_restart >= self.backoff_seconds:
                self._restarts += 1
                self._last_restart = now
                logger.warning(
                    "attempting controlled restart (%d/%d)", self._restarts, self.max_restarts
                )
                try:
                    self.on_restart()
                except Exception as exc:  # noqa: BLE001
                    logger.error("restart failed: %s", exc)

    def _record_failure(self, now: float) -> None:
        try:
            self.db.set_state("watchdog_failures", str(self._restarts + 1))
            self.db.set_state("watchdog_last_failure", str(now))
        except Exception:  # noqa: BLE001
            pass
