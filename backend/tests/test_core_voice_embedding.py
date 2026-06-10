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


def test_pick_clean_snippets_stops_once_target_total_reached():
    from app.core.voice_embedding import pick_clean_snippets

    results = [
        _tr("Speaker 0", 0, 8000),  # exactly fills the 8s target
        _tr("Speaker 1", 8000, 9000),
        _tr("Speaker 0", 9000, 12000),  # would overshoot; must be dropped
    ]
    spans = pick_clean_snippets(results, "Speaker 0", target_total_s=8.0, min_total_s=6.0)
    assert spans == [(0, 8000)]


def test_pick_clean_snippets_truncates_run_exceeding_target():
    from app.core.voice_embedding import pick_clean_snippets

    # One 40s run against the default 30s target -> truncated, not dropped.
    results = [_tr("Speaker 0", 0, 40_000)]
    assert pick_clean_snippets(results, "Speaker 0") == [(0, 30_000)]


class _FakeEcapaEncoder:
    """Stands in for the SpeechBrain encoder: records inputs, returns a constant tensor."""

    def __init__(self) -> None:
        self.batches: list = []

    def encode_batch(self, waveform):
        import torch

        self.batches.append(waveform)
        return torch.ones(1, 1, EMBEDDING_DIM)


def test_get_model_loads_speechbrain_encoder_once_and_caches(monkeypatch):
    """First call builds the encoder via from_hparams; later calls reuse the cache."""
    import sys
    import types

    from app.core import voice_embedding

    calls: list[dict] = []
    fake_encoder = object()

    class FakeEncoderClassifier:
        @classmethod
        def from_hparams(cls, **kwargs):
            calls.append(kwargs)
            return fake_encoder

    speaker_mod = types.ModuleType("speechbrain.inference.speaker")
    speaker_mod.EncoderClassifier = FakeEncoderClassifier
    inference_mod = types.ModuleType("speechbrain.inference")
    inference_mod.speaker = speaker_mod
    root_mod = types.ModuleType("speechbrain")
    root_mod.inference = inference_mod
    monkeypatch.setitem(sys.modules, "speechbrain", root_mod)
    monkeypatch.setitem(sys.modules, "speechbrain.inference", inference_mod)
    monkeypatch.setitem(sys.modules, "speechbrain.inference.speaker", speaker_mod)
    monkeypatch.setattr(voice_embedding, "_model", None)

    first = voice_embedding._get_model()
    second = voice_embedding._get_model()

    assert first is fake_encoder
    assert second is fake_encoder
    assert len(calls) == 1  # cached after the first load
    assert calls[0]["source"] == voice_embedding.HF_MODEL_SOURCE
    assert calls[0]["run_opts"] == {"device": "cpu"}
    assert calls[0]["savedir"].endswith(".cache/speechbrain/spkrec-ecapa-voxceleb")


def test_compute_voice_embedding_spans_normalizes_fake_model_output(monkeypatch):
    """Spans are concatenated (degenerate ones skipped) and the output L2-normalized."""
    import torch

    from app.core.voice_embedding import compute_voice_embedding_spans

    fake = _FakeEcapaEncoder()
    monkeypatch.setattr("app.core.voice_embedding._get_model", lambda: fake)

    with tempfile.TemporaryDirectory() as tmp:
        wav_path = Path(tmp) / "tone.wav"
        _write_sine_wav(wav_path, duration_s=2.0, freq_hz=220.0)
        # (700, 700) is degenerate and must be skipped, not crash.
        emb = compute_voice_embedding_spans(wav_path, [(0, 500), (700, 700), (1000, 1500)])

    assert len(emb) == EMBEDDING_DIM
    expected = 1.0 / math.sqrt(EMBEDDING_DIM)
    assert emb == pytest.approx([expected] * EMBEDDING_DIM)
    assert len(fake.batches) == 1  # file decoded and encoded exactly once
    waveform = fake.batches[0]
    assert tuple(waveform.shape) == (1, 16_000)  # 500ms + 500ms at 16 kHz, mono
    assert waveform.dtype == torch.float32
    assert float(waveform.abs().max()) <= 1.0  # samples scaled into [-1, 1]


def test_compute_voice_embedding_single_slice_uses_span_pipeline(monkeypatch):
    fake = _FakeEcapaEncoder()
    monkeypatch.setattr("app.core.voice_embedding._get_model", lambda: fake)

    with tempfile.TemporaryDirectory() as tmp:
        wav_path = Path(tmp) / "tone.wav"
        _write_sine_wav(wav_path, duration_s=2.0, freq_hz=220.0)
        emb = compute_voice_embedding(wav_path, 250, 1250)

    assert len(emb) == EMBEDDING_DIM
    assert tuple(fake.batches[0].shape) == (1, 16_000)  # exactly the requested 1s slice


def test_compute_voice_embedding_spans_rejects_all_degenerate_spans(monkeypatch):
    from app.core.voice_embedding import compute_voice_embedding_spans

    monkeypatch.setattr(
        "app.core.voice_embedding._get_model",
        lambda: pytest.fail("model must not be loaded when no audio was sliced"),
    )

    with tempfile.TemporaryDirectory() as tmp:
        wav_path = Path(tmp) / "tone.wav"
        _write_sine_wav(wav_path, duration_s=1.0, freq_hz=220.0)
        with pytest.raises(ValueError, match="All spans were empty after slicing"):
            compute_voice_embedding_spans(wav_path, [(400, 400), (900, 100)])
