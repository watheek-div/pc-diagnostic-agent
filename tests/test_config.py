"""Configuration loading and validation tests."""

import os

from agent.config import Config, load_config


def test_defaults():
    cfg = Config().validated()
    assert cfg.collection_interval_seconds == 30
    assert cfg.retention_hours == 24
    assert cfg.logging_level == "INFO"


def test_invalid_interval_falls_back_to_default():
    cfg = Config(collection_interval_seconds=99).validated()
    assert cfg.collection_interval_seconds == 30


def test_allowed_intervals():
    for interval in (10, 30, 60):
        cfg = Config(collection_interval_seconds=interval).validated()
        assert cfg.collection_interval_seconds == interval


def test_from_dict_nested_keys():
    cfg = Config.from_dict(
        {
            "collection_interval_seconds": 60,
            "temperature": {"warning_celsius": 80},
            "thresholds": {"memory_warning_percent": 92},
            "logging": {"level": "DEBUG"},
        }
    ).validated()
    assert cfg.collection_interval_seconds == 60
    assert cfg.temperature_warning_celsius == 80
    assert cfg.memory_warning_percent == 92
    assert cfg.logging_level == "DEBUG"


def test_invalid_log_level_sanitized():
    cfg = Config(logging_level="VERBOSE").validated()
    assert cfg.logging_level == "INFO"


def test_critical_temp_below_warning_is_fixed():
    cfg = Config(temperature_warning_celsius=90, temperature_critical_celsius=80).validated()
    assert cfg.temperature_critical_celsius > cfg.temperature_warning_celsius


def test_load_config_missing_file_returns_defaults(tmp_path):
    cfg = load_config(str(tmp_path / "missing.yaml"))
    assert cfg.collection_interval_seconds == 30


def test_load_config_file(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text("collection_interval_seconds: 10\nretention_hours: 48\n", encoding="utf-8")
    cfg = load_config(str(path))
    assert cfg.collection_interval_seconds == 10
    assert cfg.retention_hours == 48
