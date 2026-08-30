"""Collector failure isolation tests."""

from collectors.base import run_isolated
from collectors.cpu import CpuCollector
from collectors.memory import MemoryCollector


def test_run_isolated_returns_value():
    assert run_isolated(lambda: 42) == 42


def test_run_isolated_swallows_exception():
    def boom():
        raise RuntimeError("collector exploded")

    assert run_isolated(boom) is None


def test_collector_failure_does_not_stop_others():
    # A raising collector must not prevent a healthy collector from returning data.
    results = []
    for fn in (lambda: (_ for _ in ()).throw(RuntimeError()), lambda: "ok"):
        results.append(run_isolated(fn))
    assert results == [None, "ok"]


def test_real_collectors_return_expected_shape():
    cpu = CpuCollector().collect(0.0, 1)
    assert "metrics_cpu" in cpu
    mem = MemoryCollector().collect(0.0, 1)
    assert "metrics_memory" in mem
    assert "memory_percent" in mem["metrics_memory"][0]
