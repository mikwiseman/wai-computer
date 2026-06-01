"""Tests for app/core/voice_embedding.py — ECAPA-TDNN inference + snippet picking."""

from __future__ import annotations

import math
import struct
import tempfile
import wave
from pathlib import Path

import pytest

from app.core.transcript_utils import TranscriptResult
from app.core.voice_embedding import (
    EMBEDDING_DIM,
    compute_voice_embedding,
    pick_clean_snippet,
)


def _write_sine_wav(path: Path, *, duration_s: float, freq_hz: float, sr: int = 16_000) -> None:
    """Write a mono 16-bit PCM sine wave to ``path``."""
    n_samples = int(duration_s * sr)
    with wave.open(str(path), "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        for i in range(n_samples):
            value = int(0.5 * 32767 * math.sin(2 * math.pi * freq_hz * i / sr))
            wf.writeframesraw(struct.pack("<h", value))


def _tr(speaker: str | None, start_ms: int, end_ms: int) -> TranscriptResult:
    return TranscriptResult(
        text="",
        speaker=speaker,
        is_final=True,
        start_ms=start_ms,
        end_ms=end_ms,
        confidence=0.0,
    )


def test_pick_clean_snippet_returns_longest_run():
    results = [
        _tr("Speaker 0", 0, 1000),
        _tr("Speaker 0", 1000, 2000),
        _tr("Speaker 1", 2000, 3000),
        _tr("Speaker 0", 3000, 9000),  # longest run for Speaker 0
        _tr("Speaker 0", 9000, 9500),
    ]
    span = pick_clean_snippet(results, "Speaker 0", min_s=5.0)
    assert span == (3000, 9500)


def test_pick_clean_snippet_caps_at_max_s():
    results = [
        _tr("Speaker 0", 0, 30_000),
    ]
    span = pick_clean_snippet(results, "Speaker 0", min_s=5.0, max_s=15.0)
    assert span == (0, 15_000)


def test_pick_clean_snippet_returns_none_when_too_short():
    results = [
        _tr("Speaker 0", 0, 2000),
        _tr("Speaker 1", 2000, 4000),
    ]
    assert pick_clean_snippet(results, "Speaker 0", min_s=5.0) is None


def test_pick_clean_snippet_speaker_not_present():
    results = [_tr("Speaker 0", 0, 6000)]
    assert pick_clean_snippet(results, "Speaker 99", min_s=5.0) is None


def test_pick_clean_snippet_empty_input():
    assert pick_clean_snippet([], "Speaker 0") is None


@pytest.mark.slow
def test_compute_voice_embedding_is_deterministic_and_normalized():
    """Identical audio → identical embedding; embedding is 192-d L2-normalized.

    Marked slow because it downloads the ECAPA model (~80MB) on first run.
    """
    with tempfile.TemporaryDirectory() as tmp:
        wav_path = Path(tmp) / "sine.wav"
        _write_sine_wav(wav_path, duration_s=6.0, freq_hz=220.0)

        emb_a = compute_voice_embedding(wav_path, 0, 6000)
        emb_b = compute_voice_embedding(wav_path, 0, 6000)

    assert len(emb_a) == EMBEDDING_DIM == 192
    assert emb_a == emb_b
    norm = math.sqrt(sum(x * x for x in emb_a))
    assert norm == pytest.approx(1.0, abs=1e-4)


@pytest.mark.slow
def test_compute_voice_embedding_differs_across_distinct_signals():
    """Different signals yield different embeddings."""
    with tempfile.TemporaryDirectory() as tmp:
        a = Path(tmp) / "a.wav"
        b = Path(tmp) / "b.wav"
        _write_sine_wav(a, duration_s=6.0, freq_hz=220.0)
        _write_sine_wav(b, duration_s=6.0, freq_hz=880.0)

        emb_a = compute_voice_embedding(a, 0, 6000)
        emb_b = compute_voice_embedding(b, 0, 6000)

    cosine = sum(x * y for x, y in zip(emb_a, emb_b))
    assert cosine < 0.999


def test_compute_voice_embedding_rejects_empty_range():
    from app.core.voice_embedding import compute_voice_embedding

    with pytest.raises(ValueError, match="Empty snippet range"):
        compute_voice_embedding("ignored.wav", 1000, 1000)


def test_compute_voice_embedding_spans_rejects_no_spans():
    from app.core.voice_embedding import compute_voice_embedding_spans

    with pytest.raises(ValueError, match="No spans provided"):
        compute_voice_embedding_spans("ignored.wav", [])


def test_pick_clean_snippets_returns_none_without_results():
    from app.core.voice_embedding import pick_clean_snippets

    assert pick_clean_snippets([], "Speaker 0") is None


def test_pick_clean_snippets_returns_none_when_label_absent():
    from app.core.voice_embedding import pick_clean_snippets

    results = [_tr("Speaker 1", 0, 8000)]
    assert pick_clean_snippets(results, "Speaker 0") is None


def test_pick_clean_snippets_returns_none_below_min_total():
    from app.core.voice_embedding import pick_clean_snippets

    # only 2s for Speaker 0, below the 6s default minimum -> None
    results = [_tr("Speaker 0", 0, 2000)]
    assert pick_clean_snippets(results, "Speaker 0") is None


def test_pick_clean_snippets_accumulates_runs_sorted_in_order():
    from app.core.voice_embedding import pick_clean_snippets

    results = [
        _tr("Speaker 0", 0, 8000),  # 8s run
        _tr("Speaker 1", 8000, 9000),
        _tr("Speaker 0", 9000, 12000),  # 3s run
    ]
    spans = pick_clean_snippets(results, "Speaker 0", target_total_s=30.0, min_total_s=6.0)
    assert spans == [(0, 8000), (9000, 12000)]  # transcript order, both runs picked
