"""drop deprecated STT models and reset users to the new curated set

Revision ID: 20260518_160000
Revises: 20260518_150000
Create Date: 2026-05-18 16:00:00.000000+00:00

Resets any user pinned to a now-dropped transcription model id back to the
curated default (ElevenLabs Scribe v2 / Scribe v2 Realtime). Drops:

- OpenAI gpt-4o-transcribe family (retired Feb / June 2026).
- Legacy AssemblyAI streaming variants (universal-streaming-*, whisper-rt).
- AssemblyAI Universal-3 Pro Streaming via Inworld (6-language limit; fails our
  ≥50-language curation bar).
- Inworld first-party inworld-stt-1 (English-only fully supported).
- Groq Whisper Large v3 / v3 Turbo via Inworld (dropped per product direction).
"""

from typing import Sequence, Union  # noqa: F401

import sqlalchemy as sa
from alembic import op

revision: str = "20260518_160000"
down_revision: Union[str, None] = "20260518_150000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Curated defaults (must match app.core.transcription_options).
DEFAULT_REALTIME_PROVIDER = "elevenlabs"
DEFAULT_REALTIME_MODEL = "scribe_v2_realtime"
DEFAULT_FILE_PROVIDER = "elevenlabs"
DEFAULT_FILE_MODEL = "scribe_v2"

# Models that should no longer appear in any user's saved preferences.
DROPPED_FILE_MODELS = (
    # OpenAI batch transcription — all retired.
    ("openai", "gpt-4o-transcribe"),
    ("openai", "gpt-4o-mini-transcribe"),
    ("openai", "gpt-4o-transcribe-diarize"),
    # Inworld first-party + Groq batch options removed from the new registry.
    ("inworld", "inworld/inworld-stt-1"),
    ("inworld", "groq/whisper-large-v3"),
    ("inworld", "groq/whisper-large-v3-turbo"),
)

DROPPED_REALTIME_MODELS = (
    # Inworld first-party — English-only.
    ("inworld", "inworld/inworld-stt-1"),
    # Legacy + 6-language-limited AssemblyAI variants.
    ("inworld", "assemblyai/u3-rt-pro"),
    ("inworld", "assemblyai/universal-streaming-multilingual"),
    ("inworld", "assemblyai/universal-streaming-english"),
    ("inworld", "assemblyai/whisper-rt"),
)


def _build_reset_clause(
    column_provider: str, column_model: str, dropped: tuple[tuple[str, str], ...]
) -> str:
    """Build a SQL ``OR``-joined predicate matching every (provider, model) pair."""
    pieces = [
        f"({column_provider} = '{provider}' AND {column_model} = '{model}')"
        for provider, model in dropped
    ]
    return " OR ".join(pieces)


def upgrade() -> None:
    # Reset file_stt for users pinned to a dropped batch model.
    file_predicate = _build_reset_clause(
        "file_stt_provider", "file_stt_model", DROPPED_FILE_MODELS
    )
    op.execute(
        sa.text(
            f"""
            UPDATE users
            SET file_stt_provider = :provider,
                file_stt_model = :model
            WHERE {file_predicate}
            """
        ).bindparams(provider=DEFAULT_FILE_PROVIDER, model=DEFAULT_FILE_MODEL)
    )

    # Reset dictation_live_stt for users pinned to a dropped realtime model.
    dictation_predicate = _build_reset_clause(
        "dictation_live_stt_provider", "dictation_live_stt_model", DROPPED_REALTIME_MODELS
    )
    op.execute(
        sa.text(
            f"""
            UPDATE users
            SET dictation_live_stt_provider = :provider,
                dictation_live_stt_model = :model
            WHERE {dictation_predicate}
            """
        ).bindparams(provider=DEFAULT_REALTIME_PROVIDER, model=DEFAULT_REALTIME_MODEL)
    )

    # Reset recording_live_stt for users pinned to a dropped realtime model.
    recording_predicate = _build_reset_clause(
        "recording_live_stt_provider", "recording_live_stt_model", DROPPED_REALTIME_MODELS
    )
    op.execute(
        sa.text(
            f"""
            UPDATE users
            SET recording_live_stt_provider = :provider,
                recording_live_stt_model = :model
            WHERE {recording_predicate}
            """
        ).bindparams(provider=DEFAULT_REALTIME_PROVIDER, model=DEFAULT_REALTIME_MODEL)
    )


def downgrade() -> None:
    # Forward-only: we cannot recover the original user choices because we did
    # not snapshot them before overwriting. Restoring previous defaults is the
    # most we can do — operators who need the prior values must restore from a
    # backup.
    pass
