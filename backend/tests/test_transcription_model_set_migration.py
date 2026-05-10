"""Regression tests for stable transcription preference migrations."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

from sqlalchemy.sql.elements import TextClause


def _load_migration(filename: str) -> ModuleType:
    path = (
        Path(__file__).resolve().parents[1]
        / "app"
        / "db"
        / "migrations"
        / "versions"
        / filename
    )
    spec = importlib.util.spec_from_file_location(filename.removesuffix(".py"), path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_stable_transcription_model_set_migration_overwrites_existing_choices(monkeypatch):
    """Stable branch should reset saved model choices to the locked production set."""
    migration = _load_migration("20260510_130000_enforce_stable_transcription_model_set.py")
    executed: list[TextClause] = []
    altered: list[dict[str, object]] = []

    monkeypatch.setattr(migration.op, "execute", executed.append)
    monkeypatch.setattr(
        migration.op,
        "alter_column",
        lambda *args, **kwargs: altered.append({"args": args, "kwargs": kwargs}),
    )

    migration.upgrade()

    assert executed
    statement = str(executed[0])
    assert "dictation_live_stt_provider = :dictation_provider" in statement
    assert "recording_live_stt_provider = :recording_provider" in statement
    assert "file_stt_provider = :file_provider" in statement
    assert "dictation_post_filter_enabled = true" in statement
    assert "dictation_post_filter_model = :post_filter_model" in statement
    defaults = {change["args"][1]: change["kwargs"]["server_default"] for change in altered}
    assert defaults["dictation_live_stt_provider"] == "elevenlabs"
    assert defaults["dictation_live_stt_model"] == "scribe_v2_realtime"
    assert defaults["recording_live_stt_provider"] == "elevenlabs"
    assert defaults["recording_live_stt_model"] == "scribe_v2_realtime"
    assert defaults["file_stt_provider"] == "elevenlabs"
    assert defaults["file_stt_model"] == "scribe_v2"
    assert defaults["dictation_post_filter_enabled"] == "true"
    assert defaults["dictation_post_filter_provider"] == "anthropic"
    assert defaults["dictation_post_filter_model"] == "claude-3-5-haiku-20241022"


def test_anthropic_post_filter_model_migration_rewrites_invalid_ids(monkeypatch):
    """Invalid Anthropic model ids should be rewritten to official pinned ids."""
    migration = _load_migration("20260510_170000_fix_anthropic_post_filter_models.py")
    executed: list[TextClause] = []
    altered: list[dict[str, object]] = []

    monkeypatch.setattr(migration.op, "execute", executed.append)
    monkeypatch.setattr(
        migration.op,
        "alter_column",
        lambda *args, **kwargs: altered.append({"args": args, "kwargs": kwargs}),
    )

    migration.upgrade()

    assert executed
    statement = str(executed[0])
    assert "claude-haiku-4-5-20251001" in statement
    assert "claude-sonnet-4-6" in statement
    assert "claude-opus-4-7" in statement
    assert "dictation_post_filter_model = CASE" in statement
    assert altered[0]["kwargs"]["server_default"] == "claude-3-5-haiku-20241022"
