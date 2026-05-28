"""Tests for app.core.voice_embedding helpers and app.core.voice_identification
flow. We avoid loading the SpeechBrain model — instead mocking
compute_voice_embedding entirely. pick_clean_snippet is pure logic and is
tested directly."""

from __future__ import annotations

import time
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from app.core.transcript_utils import TranscriptResult
from app.core.voice_embedding import (
    EMBEDDING_DIM,
    MODEL_NAME,
    TARGET_SAMPLE_RATE,
    pick_clean_snippet,
)
from app.core.voice_identification import (
    DEFAULT_MATCH_THRESHOLD,
    _best_voiceprint_match,
    identify_speakers_for_recording,
    store_voiceprint,
)


def _tr(speaker: str | None, start_ms: int, end_ms: int) -> TranscriptResult:
    return TranscriptResult(
        text="hi", speaker=speaker, is_final=True,
        start_ms=start_ms, end_ms=end_ms, confidence=0.9,
    )


# ---------------------------------------------------------------------------
# pick_clean_snippet (pure logic)
# ---------------------------------------------------------------------------


def test_pick_snippet_empty_results_returns_none() -> None:
    assert pick_clean_snippet([], "Speaker 1") is None


def test_pick_snippet_no_matching_speaker_returns_none() -> None:
    results = [_tr("Speaker 1", 0, 1000)]
    assert pick_clean_snippet(results, "Speaker 2") is None


def test_pick_snippet_too_short_returns_none() -> None:
    # Need ≥5s; this is only 2s.
    results = [_tr("Speaker 1", 0, 2000)]
    assert pick_clean_snippet(results, "Speaker 1") is None


def test_pick_snippet_returns_longest_contiguous_run() -> None:
    results = [
        _tr("Speaker 1", 0, 6000),       # 6s run
        _tr("Speaker 2", 6000, 7000),    # speaker switch
        _tr("Speaker 1", 7000, 9000),    # 2s run — too short alone
    ]
    span = pick_clean_snippet(results, "Speaker 1")
    assert span == (0, 6000)


def test_pick_snippet_caps_at_max_seconds() -> None:
    # 30s run; max is 15s by default.
    results = [_tr("Speaker 1", 0, 30_000)]
    span = pick_clean_snippet(results, "Speaker 1")
    assert span == (0, 15_000)


def test_pick_snippet_custom_thresholds() -> None:
    results = [_tr("Speaker 1", 0, 3000)]
    # With min_s=2, the 3s run qualifies
    span = pick_clean_snippet(results, "Speaker 1", min_s=2.0, max_s=10.0)
    assert span == (0, 3000)


def test_pick_snippet_picks_later_run_when_longer() -> None:
    results = [
        _tr("Speaker 1", 0, 5500),       # 5.5s
        _tr("Speaker 2", 5500, 6000),
        _tr("Speaker 1", 6000, 14000),   # 8s — longer
    ]
    span = pick_clean_snippet(results, "Speaker 1")
    assert span == (6000, 14000)


def test_pick_snippet_speaker_switch_breaks_run() -> None:
    """Confirms a single speaker block is not counted across a different
    speaker in the middle (line 105-108: else branch)."""
    results = [
        _tr("Speaker 1", 0, 2000),
        _tr("Speaker 2", 2000, 2500),
        _tr("Speaker 1", 2500, 4000),
        _tr("Speaker 2", 4000, 4500),
        _tr("Speaker 1", 4500, 10000),   # only this 5.5s qualifies
    ]
    span = pick_clean_snippet(results, "Speaker 1")
    assert span == (4500, 10000)


def test_pick_snippet_none_speakers_ignored() -> None:
    """Speaker None in results doesn't match a target string."""
    results = [
        _tr(None, 0, 6000),
        _tr("Speaker 1", 6000, 12000),
    ]
    span = pick_clean_snippet(results, "Speaker 1")
    assert span == (6000, 12000)


# ---------------------------------------------------------------------------
# voice_embedding module constants
# ---------------------------------------------------------------------------


def test_voice_embedding_constants() -> None:
    assert MODEL_NAME == "ecapa-tdnn-voxceleb-v1"
    assert EMBEDDING_DIM == 192
    assert TARGET_SAMPLE_RATE == 16_000


# ---------------------------------------------------------------------------
# identify_speakers_for_recording (mocked embedding)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_identify_returns_empty_when_no_speakers() -> None:
    """Empty results or all-None speakers → empty mapping."""
    from unittest.mock import MagicMock

    from sqlalchemy.ext.asyncio import AsyncSession

    db = MagicMock(spec=AsyncSession)
    out = await identify_speakers_for_recording(
        db=db, user_id=uuid.uuid4(), staged_audio_path=Path("/tmp/x.wav"),
        transcript_results=[],
    )
    assert out == {}

    # All speakers None
    results = [_tr(None, 0, 5000)]
    out = await identify_speakers_for_recording(
        db=db, user_id=uuid.uuid4(), staged_audio_path=Path("/tmp/x.wav"),
        transcript_results=results,
    )
    assert out == {}


@pytest.mark.asyncio
async def test_identify_assigns_none_when_no_clean_snippet() -> None:
    """Speaker with no ≥5s run → None assignment (line 60)."""
    from unittest.mock import MagicMock

    from sqlalchemy.ext.asyncio import AsyncSession

    db = MagicMock(spec=AsyncSession)
    results = [_tr("Speaker 1", 0, 1000)]  # only 1s — too short
    out = await identify_speakers_for_recording(
        db=db, user_id=uuid.uuid4(), staged_audio_path=Path("/tmp/x.wav"),
        transcript_results=results,
    )
    assert out == {"Speaker 1": None}


@pytest.mark.asyncio
async def test_identify_handles_embedding_failure() -> None:
    """Embedding computation raises → assignment is None (lines 68-72)."""
    from unittest.mock import MagicMock

    from sqlalchemy.ext.asyncio import AsyncSession

    db = MagicMock(spec=AsyncSession)
    results = [_tr("Speaker 1", 0, 10_000)]  # 10s — passes pick_clean_snippet

    with patch(
        "app.core.voice_identification.compute_voice_embedding_spans",
        side_effect=RuntimeError("model load failed"),
    ):
        out = await identify_speakers_for_recording(
            db=db, user_id=uuid.uuid4(), staged_audio_path=Path("/tmp/x.wav"),
            transcript_results=results,
        )
    assert out == {"Speaker 1": None}


@pytest.mark.asyncio
async def test_identify_disabled_returns_unassigned_without_loading_model() -> None:
    from unittest.mock import MagicMock

    from sqlalchemy.ext.asyncio import AsyncSession

    db = MagicMock(spec=AsyncSession)
    results = [_tr("Speaker 1", 0, 10_000)]

    with patch("app.core.voice_identification.compute_voice_embedding_spans") as compute:
        out = await identify_speakers_for_recording(
            db=db,
            user_id=uuid.uuid4(),
            staged_audio_path=Path("/tmp/x.wav"),
            transcript_results=results,
            enabled=False,
        )

    compute.assert_not_called()
    assert out == {"Speaker 1": None}


@pytest.mark.asyncio
async def test_identify_times_out_embedding_and_continues() -> None:
    """Embedding timeout is non-fatal: import/transcription must still finish."""
    from unittest.mock import MagicMock

    from sqlalchemy.ext.asyncio import AsyncSession

    db = MagicMock(spec=AsyncSession)
    results = [_tr("Speaker 1", 0, 10_000)]

    def slow_embedding(*_: object) -> list[float]:
        time.sleep(0.05)
        return [0.5] * EMBEDDING_DIM

    with patch(
        "app.core.voice_identification.compute_voice_embedding_spans",
        side_effect=slow_embedding,
    ):
        out = await identify_speakers_for_recording(
            db=db,
            user_id=uuid.uuid4(),
            staged_audio_path=Path("/tmp/x.wav"),
            transcript_results=results,
            embedding_timeout_seconds=0.001,
        )

    assert out == {"Speaker 1": None}


@pytest.mark.asyncio
async def test_identify_calls_best_match_when_embedding_succeeds() -> None:
    """Successful embedding → _best_voiceprint_match invoked, assignment recorded."""
    from unittest.mock import MagicMock

    from sqlalchemy.ext.asyncio import AsyncSession

    db = MagicMock(spec=AsyncSession)
    person_id = uuid.uuid4()
    results = [_tr("Speaker 1", 0, 10_000)]

    fake_embedding = [0.5] * EMBEDDING_DIM
    with (
        patch(
            "app.core.voice_identification.compute_voice_embedding_spans",
            return_value=fake_embedding,
        ),
        patch(
            "app.core.voice_identification._best_voiceprint_match",
            new=AsyncMock(return_value=(person_id, 0.85)),
        ),
    ):
        out = await identify_speakers_for_recording(
            db=db, user_id=uuid.uuid4(), staged_audio_path=Path("/tmp/x.wav"),
            transcript_results=results,
        )

    assert out == {"Speaker 1": (person_id, 0.85)}


# ---------------------------------------------------------------------------
# _best_voiceprint_match
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_best_match_returns_none_when_no_rows() -> None:
    """No voiceprints in DB → None."""
    from unittest.mock import MagicMock

    from sqlalchemy.ext.asyncio import AsyncSession

    db = MagicMock(spec=AsyncSession)
    result_mock = MagicMock()
    result_mock.first = MagicMock(return_value=None)
    db.execute = AsyncMock(return_value=result_mock)

    out = await _best_voiceprint_match(
        db, uuid.uuid4(), [0.1] * EMBEDDING_DIM, DEFAULT_MATCH_THRESHOLD,
    )
    assert out is None


@pytest.mark.asyncio
async def test_best_match_returns_none_below_threshold() -> None:
    """Row found but similarity < threshold → None."""
    from unittest.mock import MagicMock

    from sqlalchemy.ext.asyncio import AsyncSession

    db = MagicMock(spec=AsyncSession)
    result_mock = MagicMock()
    person_id = uuid.uuid4()
    result_mock.first = MagicMock(
        return_value=(person_id, 0.20)
    )  # well below DEFAULT_MATCH_THRESHOLD
    db.execute = AsyncMock(return_value=result_mock)

    out = await _best_voiceprint_match(
        db, uuid.uuid4(), [0.1] * EMBEDDING_DIM, threshold=DEFAULT_MATCH_THRESHOLD,
    )
    assert out is None


@pytest.mark.asyncio
async def test_best_match_returns_none_when_similarity_is_null() -> None:
    """Row found but similarity is None → None."""
    from unittest.mock import MagicMock

    from sqlalchemy.ext.asyncio import AsyncSession

    db = MagicMock(spec=AsyncSession)
    result_mock = MagicMock()
    person_id = uuid.uuid4()
    result_mock.first = MagicMock(return_value=(person_id, None))
    db.execute = AsyncMock(return_value=result_mock)

    out = await _best_voiceprint_match(
        db, uuid.uuid4(), [0.1] * EMBEDDING_DIM, threshold=DEFAULT_MATCH_THRESHOLD,
    )
    assert out is None


@pytest.mark.asyncio
async def test_best_match_returns_pair_above_threshold() -> None:
    """Row found with similarity ≥ threshold → (person_id, similarity)."""
    from unittest.mock import MagicMock

    from sqlalchemy.ext.asyncio import AsyncSession

    db = MagicMock(spec=AsyncSession)
    result_mock = MagicMock()
    person_id = uuid.uuid4()
    result_mock.first = MagicMock(return_value=(person_id, 0.92))
    db.execute = AsyncMock(return_value=result_mock)

    out = await _best_voiceprint_match(
        db, uuid.uuid4(), [0.1] * EMBEDDING_DIM, threshold=DEFAULT_MATCH_THRESHOLD,
    )
    assert out == (person_id, 0.92)


# ---------------------------------------------------------------------------
# store_voiceprint
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_store_voiceprint_returns_none_when_no_clean_snippet() -> None:
    from unittest.mock import MagicMock

    from sqlalchemy.ext.asyncio import AsyncSession

    db = MagicMock(spec=AsyncSession)
    db.execute = AsyncMock()
    # only 1s — too short for clean snippet (min 5s)
    results = [_tr("Speaker 1", 0, 1000)]

    out = await store_voiceprint(
        db=db, user_id=uuid.uuid4(), person_id=uuid.uuid4(),
        staged_audio_path=Path("/tmp/x.wav"),
        transcript_results=results,
        raw_label="Speaker 1",
        source_recording_id=None,
    )
    assert out is None
    db.execute.assert_not_called()


@pytest.mark.asyncio
async def test_store_voiceprint_inserts_and_returns_id() -> None:
    from unittest.mock import MagicMock

    from sqlalchemy.ext.asyncio import AsyncSession

    db = MagicMock(spec=AsyncSession)
    db.execute = AsyncMock()
    results = [_tr("Speaker 1", 0, 10_000)]

    fake_embedding = [0.5] * EMBEDDING_DIM
    # store_voiceprint goes through store_voiceprint_from_path, which still
    # uses the single-span compute_voice_embedding entry point.
    with patch(
        "app.core.voice_identification.compute_voice_embedding",
        return_value=fake_embedding,
    ):
        out = await store_voiceprint(
            db=db, user_id=uuid.uuid4(), person_id=uuid.uuid4(),
            staged_audio_path=Path("/tmp/x.wav"),
            transcript_results=results,
            raw_label="Speaker 1",
            source_recording_id=uuid.uuid4(),
        )

    assert out is not None
    assert isinstance(out, uuid.UUID)
    db.execute.assert_called_once()
