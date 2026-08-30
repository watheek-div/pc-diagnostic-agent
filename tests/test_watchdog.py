"""Watchdog tests (no threads — the check logic is tested directly)."""

import time

from watchdog.watchdog import Watchdog


class FakeDB:
    def __init__(self, heartbeat=None):
        self.heartbeat = heartbeat
        self.states = {}

    def get_heartbeat(self):
        return self.heartbeat

    def set_state(self, key, value):
        self.states[key] = value


def test_no_heartbeat_yet_is_ignored():
    db = FakeDB(heartbeat=None)
    restarts = []
    w = Watchdog(db, on_restart=lambda: restarts.append(1))
    w._check()
    assert restarts == []


def test_fresh_heartbeat_is_ignored():
    db = FakeDB(heartbeat=time.time())
    restarts = []
    w = Watchdog(db, on_restart=lambda: restarts.append(1), stale_after=90.0)
    w._check()
    assert restarts == []
    assert not w.stale_detected.is_set()


def test_stale_heartbeat_triggers_restart():
    db = FakeDB(heartbeat=time.time() - 200)
    restarts = []
    w = Watchdog(db, on_restart=lambda: restarts.append(1), stale_after=90.0, backoff_seconds=0)
    w._check()
    assert restarts == [1]
    assert w.stale_detected.is_set()


def test_backoff_prevents_restart_loop():
    db = FakeDB(heartbeat=time.time() - 200)
    restarts = []
    w = Watchdog(db, on_restart=lambda: restarts.append(1), stale_after=90.0, backoff_seconds=3600)
    w._check()
    w._check()
    assert restarts == [1]


def test_max_restarts_enforced():
    db = FakeDB(heartbeat=time.time() - 200)
    restarts = []
    w = Watchdog(db, on_restart=lambda: restarts.append(1), stale_after=90.0, max_restarts=2, backoff_seconds=0)
    for _ in range(5):
        w._check()
    assert len(restarts) == 2
