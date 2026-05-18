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
    assert defaults["dictation_post_filter_model"] == "claude-haiku-4-5"


def test_anthropic_post_filter_model_migration_preserves_current_ids(monkeypatch):
    """Current Anthropic model ids should remain the stable defaults."""
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
    assert "claude-haiku-4-5" in statement
    assert "claude-haiku-4-5-20251001" in statement
    assert "claude-sonnet-4-6" in statement
    assert "claude-opus-4-7" in statement
    assert "dictation_post_filter_model = CASE" in statement
    assert altered[0]["kwargs"]["server_default"] == "claude-haiku-4-5"


def test_latest_anthropic_post_filter_model_migration_restores_current_ids(monkeypatch):
    """Older conservative defaults should be rewritten to current Anthropic ids."""
    migration = _load_migration("20260510_180000_restore_latest_anthropic_post_filter_models.py")
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
    assert "claude-3-5-haiku-20241022" in statement
    assert "claude-haiku-4-5-20251001" in statement
    assert "claude-sonnet-4-20250514" in statement
    assert "claude-opus-4-1-20250805" in statement
    assert "dictation_post_filter_model = CASE" in statement
    assert altered[0]["kwargs"]["server_default"] == "claude-haiku-4-5"


def test_drop_deprecated_stt_models_migration_resets_users(monkeypatch):
    """May 18 cleanup must reset users on dropped models to the ElevenLabs defaults."""
    migration = _load_migration("20260518_160000_drop_deprecated_stt_models.py")
    executed: list[TextClause] = []

    monkeypatch.setattr(migration.op, "execute", executed.append)

    migration.upgrade()

    # Three UPDATE statements: file_stt, dictation_live_stt, recording_live_stt.
    assert len(executed) == 3

    statements = [str(stmt) for stmt in executed]
    file_sql = next(s for s in statements if "file_stt_provider" in s and "file_stt_model" in s)
    assert "gpt-4o-transcribe" in file_sql
    assert "gpt-4o-mini-transcribe" in file_sql
    assert "gpt-4o-transcribe-diarize" in file_sql
    assert "inworld/inworld-stt-1" in file_sql
    assert "groq/whisper-large-v3" in file_sql
    assert "groq/whisper-large-v3-turbo" in file_sql

    dictation_sql = next(s for s in statements if "dictation_live_stt_provider" in s)
    assert "inworld/inworld-stt-1" in dictation_sql
    assert "assemblyai/u3-rt-pro" in dictation_sql
    assert "assemblyai/universal-streaming-multilingual" in dictation_sql
    assert "assemblyai/universal-streaming-english" in dictation_sql
    assert "assemblyai/whisper-rt" in dictation_sql

    recording_sql = next(s for s in statements if "recording_live_stt_provider" in s)
    assert "inworld/inworld-stt-1" in recording_sql
    assert "assemblyai/u3-rt-pro" in recording_sql
