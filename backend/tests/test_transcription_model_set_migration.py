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


def test_soniox_dictation_default_migration(monkeypatch):
    """May 20 realtime eval should switch only default dictation users to Soniox."""
    migration = _load_migration("20260520_180000_soniox_dictation_default.py")
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
    assert "dictation_live_stt_provider = :new_provider" in statement
    assert "dictation_live_stt_model = :new_model" in statement
    assert "dictation_live_stt_provider = :old_provider" in statement
    assert "dictation_live_stt_model = :old_model" in statement
    defaults = {change["args"][1]: change["kwargs"]["server_default"] for change in altered}
    assert defaults["dictation_live_stt_provider"] == "soniox"
    assert defaults["dictation_live_stt_model"] == "stt-rt-v4"


def test_soniox_recording_live_default_migration(monkeypatch):
    """May 20 realtime eval should switch only default live-recording users to Soniox."""
    migration = _load_migration("20260520_200000_soniox_recording_live_default.py")
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
    assert "recording_live_stt_provider = :new_provider" in statement
    assert "recording_live_stt_model = :new_model" in statement
    assert "recording_live_stt_provider = :old_provider" in statement
    assert "recording_live_stt_model = :old_model" in statement
    defaults = {change["args"][1]: change["kwargs"]["server_default"] for change in altered}
    assert defaults["recording_live_stt_provider"] == "soniox"
    assert defaults["recording_live_stt_model"] == "stt-rt-v4"


def test_inworld_realtime_default_migration(monkeypatch):
    """May 21 stable release should move only Soniox-default live users to Inworld."""
    migration = _load_migration("20260521_090000_inworld_realtime_defaults.py")
    executed: list[TextClause] = []
    altered: list[dict[str, object]] = []

    monkeypatch.setattr(migration.op, "execute", executed.append)
    monkeypatch.setattr(
        migration.op,
        "alter_column",
        lambda *args, **kwargs: altered.append({"args": args, "kwargs": kwargs}),
    )

    migration.upgrade()

    assert len(executed) == 2
    dictation_statement = str(executed[0])
    recording_statement = str(executed[1])
    assert "dictation_live_stt_provider = :new_provider" in dictation_statement
    assert "dictation_live_stt_model = :new_model" in dictation_statement
    assert "dictation_live_stt_provider = :old_provider" in dictation_statement
    assert "dictation_live_stt_model = :old_model" in dictation_statement
    assert "recording_live_stt_provider = :new_provider" in recording_statement
    assert "recording_live_stt_model = :new_model" in recording_statement
    assert "recording_live_stt_provider = :old_provider" in recording_statement
    assert "recording_live_stt_model = :old_model" in recording_statement
    defaults = {change["args"][1]: change["kwargs"]["server_default"] for change in altered}
    assert defaults["dictation_live_stt_provider"] == "inworld"
    assert defaults["dictation_live_stt_model"] == "inworld/inworld-stt-1"
    assert defaults["recording_live_stt_provider"] == "inworld"
    assert defaults["recording_live_stt_model"] == "inworld/inworld-stt-1"


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
