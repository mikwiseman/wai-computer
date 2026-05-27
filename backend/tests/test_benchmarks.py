"""Tests for dictation benchmark endpoints after provider lock-down."""

from types import SimpleNamespace

from app.api.routes import benchmarks


def test_configured_file_stt_options_returns_only_elevenlabs_when_configured(monkeypatch):
    monkeypatch.setattr(
        benchmarks,
        "get_settings",
        lambda: SimpleNamespace(elevenlabs_api_key="xi-key", openai_api_key="openai-test-key"),
    )

    options = benchmarks._configured_file_stt_options()

    assert [(option.provider, option.model) for option in options] == [
        ("elevenlabs", "scribe_v2")
    ]


def test_benchmark_router_has_no_realtime_provider_battle_route():
    route_paths = {getattr(route, "path", None) for route in benchmarks.router.routes}

    assert "/benchmarks/dictation/live-battle" not in route_paths
