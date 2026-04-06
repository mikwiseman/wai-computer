"""Tests for agent metrics module."""

from app.services.agent.metrics import (
    AgentTimer,
    _counters,
    _histograms,
    get_metrics,
    increment,
    observe,
)


class TestCounters:
    def setup_method(self):
        _counters.clear()
        _histograms.clear()

    def test_increment_default(self):
        increment("test_metric")
        assert _counters["test_metric"] == 1

    def test_increment_by_value(self):
        increment("test_metric", 5)
        assert _counters["test_metric"] == 5

    def test_increment_accumulates(self):
        increment("test_metric")
        increment("test_metric")
        increment("test_metric", 3)
        assert _counters["test_metric"] == 5


class TestHistograms:
    def setup_method(self):
        _counters.clear()
        _histograms.clear()

    def test_observe_records_value(self):
        observe("latency", 1.5)
        assert _histograms["latency"] == [1.5]

    def test_observe_multiple_values(self):
        observe("latency", 1.0)
        observe("latency", 2.0)
        observe("latency", 3.0)
        assert _histograms["latency"] == [1.0, 2.0, 3.0]

    def test_observe_trims_at_1000(self):
        for i in range(1050):
            observe("latency", float(i))
        # After 1001 entries, trimmed to 500; then 49 more added = 549
        assert len(_histograms["latency"]) <= 600
        assert len(_histograms["latency"]) < 1050  # definitely trimmed


class TestGetMetrics:
    def setup_method(self):
        _counters.clear()
        _histograms.clear()

    def test_metrics_structure(self):
        metrics = get_metrics()
        assert "uptime_seconds" in metrics
        assert "timestamp" in metrics
        assert "counters" in metrics
        assert "histograms" in metrics

    def test_metrics_with_counters(self):
        increment("requests", 42)
        metrics = get_metrics()
        assert metrics["counters"]["requests"] == 42

    def test_metrics_with_histograms(self):
        observe("latency", 1.0)
        observe("latency", 2.0)
        observe("latency", 3.0)
        metrics = get_metrics()
        hist = metrics["histograms"]["latency"]
        assert hist["count"] == 3
        assert hist["avg"] == 2.0
        assert hist["min"] == 1.0
        assert hist["max"] == 3.0
        assert hist["p50"] == 2.0

    def test_metrics_empty_histograms_omitted(self):
        metrics = get_metrics()
        assert metrics["histograms"] == {}


class TestAgentTimer:
    def setup_method(self):
        _counters.clear()
        _histograms.clear()

    def test_timer_records_elapsed(self):
        with AgentTimer("test_op"):
            pass  # Instant operation
        assert len(_histograms["test_op"]) == 1
        assert _histograms["test_op"][0] >= 0
        assert _counters["test_op_count"] == 1

    def test_timer_returns_self(self):
        timer = AgentTimer("test_op")
        result = timer.__enter__()
        assert result is timer
        timer.__exit__(None, None, None)
