"""Logging configuration.

Agent logs are kept separate from diagnostic data and use rotation so the log
file never grows without bound.  No secrets or personal data should ever be
passed to the logger.
"""

from __future__ import annotations

import logging
import logging.handlers
import os

from common import paths

LEVELS = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
}

_configured = False


def resolve_level(name: str) -> int:
    return LEVELS.get(str(name).upper(), logging.INFO)


def configure_logging(level: str = "INFO", log_file: str | None = None) -> None:
    global _configured
    if _configured:
        return

    root = logging.getLogger()
    root.setLevel(resolve_level(level))

    fmt = logging.Formatter(
        "%(asctime)s %(levelname)-7s [%(threadName)s] %(name)s: %(message)s"
    )

    # Console handler is harmless when running as a service (no console is
    # attached) and useful during foreground/debug runs.
    console = logging.StreamHandler()
    console.setFormatter(fmt)
    root.addHandler(console)

    path = log_file or paths.log_file_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            path, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"
        )
        file_handler.setFormatter(fmt)
        root.addHandler(file_handler)
    except OSError as exc:  # pragma: no cover - environment specific
        logging.getLogger(__name__).warning("Could not open log file %s: %s", path, exc)

    _configured = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
