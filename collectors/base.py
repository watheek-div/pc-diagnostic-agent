"""Collector base classes and isolation helpers.

Every collector is independent.  A collector that raises must never stop the
rest of the agent, so callers use :func:`run_isolated`.
"""

from __future__ import annotations

import logging
from typing import Callable

logger = logging.getLogger(__name__)


class BaseCollector:
    name = "base"

    def collect(self, now: float, session_id: int, db=None) -> dict:
        """Return a snapshot mapping a metric table name to a list of rows."""
        raise NotImplementedError


def run_isolated(fn: Callable, *args, **kwargs):
    """Run ``fn`` and swallow/log any exception.

    Returns ``None`` on failure so a failing collector degrades gracefully.
    """
    try:
        return fn(*args, **kwargs)
    except Exception as exc:  # noqa: BLE001 - isolation boundary
        logger.warning("collector failed: %s: %s", getattr(fn, "__name__", fn), exc)
        return None
