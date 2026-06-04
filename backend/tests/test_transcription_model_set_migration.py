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


def test_dictation_post_filter_openai_migration_flips_defaults(monkeypatch):
    """May 18 LLM swap should reset post-filter rows and defaults to OpenAI."""
    migration = _load_migration("20260518_150000_dictation_post_filter_openai.py")
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
    assert "dictation_post_filter_provider = 'openai'" in statement
    assert "dictation_post_filter_model = 'gpt-5.5'" in statement
    defaults = {change["args"][1]: change["kwargs"]["server_default"] for change in altered}
    assert defaults["dictation_post_filter_provider"] == "openai"
    assert defaults["dictation_post_filter_model"] == "gpt-5.5"


def test_disable_dictation_post_filter_default_migration(monkeypatch):
    """May 20 product change should make dictation cleanup opt-in."""
    migration = _load_migration("20260520_170000_disable_dictation_post_filter_default.py")
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
    assert "dictation_post_filter_enabled = false" in str(executed[0])
    assert altered[0]["args"][1] == "dictation_post_filter_enabled"
    assert str(altered[0]["kwargs"]["server_default"]) == "false"


def test_deepgram_nova3_default_migration_resets_live_users(monkeypatch):
    """May 27 realtime swap should overwrite all live STT users to Deepgram."""
    migration = _load_migration("20260527_220000_deepgram_realtime_nova3_defaults.py")
    executed: list[TextClause] = []
    altered: list[dict[str, object]] = []

    monkeypatch.setattr(migration.op, "execute", executed.append)
    monkeypatch.setattr(
        migration.op,
        "alter_column",
        lambda *args, **kwargs: altered.append({"args": args, "kwargs": kwargs}),
    )

    migration.upgrade()

    assert len(executed) == 1
    statement = str(executed[0])
    assert "dictation_live_stt_provider = :provider" in statement
    assert "dictation_live_stt_model = :model" in statement
    assert "recording_live_stt_provider = :provider" in statement
    assert "recording_live_stt_model = :model" in statement
    assert "WHERE" not in statement

    defaults = {change["args"][1]: change["kwargs"]["server_default"] for change in altered}
    assert defaults["dictation_live_stt_provider"] == "deepgram"
    assert defaults["dictation_live_stt_model"] == "nova-3"
    assert defaults["recording_live_stt_provider"] == "deepgram"
    assert defaults["recording_live_stt_model"] == "nova-3"


def test_elevenlabs_file_stt_default_migration_resets_file_users(monkeypatch):
    """May 27 file STT lock should overwrite persisted file STT users to ElevenLabs."""
    migration = _load_migration("20260527_210000_elevenlabs_file_stt_defaults.py")
    executed: list[TextClause] = []
    altered: list[dict[str, object]] = []

    monkeypatch.setattr(migration.op, "execute", executed.append)
    monkeypatch.setattr(
        migration.op,
        "alter_column",
        lambda *args, **kwargs: altered.append({"args": args, "kwargs": kwargs}),
    )

    migration.upgrade()

    assert len(executed) == 1
    statement = str(executed[0])
    assert "file_stt_provider = :provider" in statement
    assert "file_stt_model = :model" in statement
    assert "WHERE" not in statement

    defaults = {change["args"][1]: change["kwargs"]["server_default"] for change in altered}
    assert defaults["file_stt_provider"] == "elevenlabs"
    assert defaults["file_stt_model"] == "scribe_v2"


def test_deepgram_file_stt_default_migration_resets_file_users(monkeypatch):
    """May 31 file STT swap should overwrite persisted file STT users to Deepgram."""
    migration = _load_migration("20260531_120000_deepgram_file_stt_defaults.py")
    executed: list[TextClause] = []
    altered: list[dict[str, object]] = []

    monkeypatch.setattr(migration.op, "execute", executed.append)
    monkeypatch.setattr(
        migration.op,
        "alter_column",
        lambda *args, **kwargs: altered.append({"args": args, "kwargs": kwargs}),
    )

    migration.upgrade()

    assert len(executed) == 1
    statement = str(executed[0])
    assert "file_stt_provider = :provider" in statement
    assert "file_stt_model = :model" in statement
    assert "WHERE" not in statement

    defaults = {change["args"][1]: change["kwargs"]["server_default"] for change in altered}
    assert defaults["file_stt_provider"] == "deepgram"
    assert defaults["file_stt_model"] == "nova-3"
