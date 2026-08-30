"""Configuration loading and validation.

Config is loaded from ``config.yaml`` next to the application (or a path
supplied by the caller).  Invalid values are rejected in favour of documented
safe defaults so a bad config can never prevent the service from starting.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass

import yaml

ALLOWED_INTERVALS = (10, 30, 60)
ALLOWED_LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR")


@dataclass
class Config:
    collection_interval_seconds: int = 30
    low_frequency_interval_seconds: int = 300
    retention_hours: int = 24
    incident_window_before_minutes: int = 30
    incident_window_after_minutes: int = 5

    temperature_warning_celsius: float = 85.0
    temperature_critical_celsius: float = 95.0

    cpu_warning_percent: float = 90.0
    cpu_critical_percent: float = 98.0
    memory_warning_percent: float = 90.0
    memory_critical_percent: float = 95.0
    disk_warning_percent: float = 90.0
    disk_free_gb_warning: float = 5.0

    logging_level: str = "INFO"

    config_path: str | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "Config":
        cfg = cls()
        if not isinstance(data, dict):
            return cfg

        top_level = (
            "collection_interval_seconds",
            "low_frequency_interval_seconds",
            "retention_hours",
            "incident_window_before_minutes",
            "incident_window_after_minutes",
        )
        for key in top_level:
            if key in data and data[key] is not None:
                setattr(cfg, key, data[key])

        temperature = data.get("temperature") or {}
        if isinstance(temperature, dict):
            if "warning_celsius" in temperature:
                cfg.temperature_warning_celsius = temperature["warning_celsius"]
            if "critical_celsius" in temperature:
                cfg.temperature_critical_celsius = temperature["critical_celsius"]

        thresholds = data.get("thresholds") or {}
        if isinstance(thresholds, dict):
            for key in (
                "cpu_warning_percent",
                "cpu_critical_percent",
                "memory_warning_percent",
                "memory_critical_percent",
                "disk_warning_percent",
                "disk_free_gb_warning",
            ):
                if key in thresholds and thresholds[key] is not None:
                    setattr(cfg, key, thresholds[key])

        logging_cfg = data.get("logging") or {}
        if isinstance(logging_cfg, dict) and "level" in logging_cfg:
            cfg.logging_level = logging_cfg["level"]

        return cfg

    def validated(self) -> "Config":
        if self.collection_interval_seconds not in ALLOWED_INTERVALS:
            self.collection_interval_seconds = 30
        if not isinstance(self.low_frequency_interval_seconds, int) or self.low_frequency_interval_seconds < 30:
            self.low_frequency_interval_seconds = 300
        if not isinstance(self.retention_hours, (int, float)) or self.retention_hours <= 0:
            self.retention_hours = 24
        for attr in (
            "incident_window_before_minutes",
            "incident_window_after_minutes",
        ):
            if not isinstance(getattr(self, attr), (int, float)) or getattr(self, attr) < 0:
                setattr(self, attr, 30 if attr.endswith("before_minutes") else 5)
        self.temperature_warning_celsius = float(self.temperature_warning_celsius)
        self.temperature_critical_celsius = float(self.temperature_critical_celsius)
        if self.temperature_critical_celsius <= self.temperature_warning_celsius:
            self.temperature_critical_celsius = self.temperature_warning_celsius + 10
        self.logging_level = (
            self.logging_level.upper()
            if str(self.logging_level).upper() in ALLOWED_LOG_LEVELS
            else "INFO"
        )
        return self


def load_config(path: str | None = None) -> Config:
    path = path or default_config_path()
    data: dict = {}
    if path and os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as handle:
                loaded = yaml.safe_load(handle)
            if isinstance(loaded, dict):
                data = loaded
        except (OSError, yaml.YAMLError):
            data = {}
    cfg = Config.from_dict(data)
    cfg.config_path = path
    return cfg.validated()


def default_config_path() -> str | None:
    candidates: list[str] = []
    if getattr(sys, "frozen", False):
        candidates.append(os.path.join(os.path.dirname(os.path.abspath(sys.executable)), "config.yaml"))
    here = os.path.dirname(os.path.abspath(__file__))
    candidates.extend(
        [
            os.path.join(here, "..", "config.yaml"),
            os.path.join(here, "..", "..", "config.yaml"),
        ]
    )
    for candidate in candidates:
        normalized = os.path.normpath(candidate)
        if os.path.exists(normalized):
            return normalized
    return None
