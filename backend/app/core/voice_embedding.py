"""Voice embeddings via SpeechBrain ECAPA-TDNN.

Computes 192-d L2-normalized speaker embeddings from a clean snippet of audio.
Used to identify speakers across recordings by cosine similarity in pgvector.

The model is downloaded once on first inference (~80MB) and cached in the
process. Subsequent calls reuse the loaded model.
"""

from __future__ import annotations

import logging
import os
import threading
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.core.transcript_utils import TranscriptResult

logger = logging.getLogger(__name__)

MODEL_NAME = "ecapa-tdnn-voxceleb-v1"
HF_MODEL_SOURCE = "speechbrain/spkrec-ecapa-voxceleb"
EMBEDDING_DIM = 192
TARGET_SAMPLE_RATE = 16_000

_MIN_SNIPPET_S = 5.0
_MAX_SNIPPET_S = 15.0
# Multi-span enrollment: ECAPA quality plateaus around 30s of speech.
# Accumulating multiple non-contiguous snippets of the same speaker is
# materially better than one long snippet because it spans intra-speaker
# variation across the recording.
_MULTI_TOTAL_TARGET_S = 30.0
_MULTI_MIN_TOTAL_S = 6.0

_model = None
_model_lock = threading.Lock()


def _get_model():
    """Return the lazily-loaded ECAPA-TDNN encoder, downloading on first use."""
    global _model
    if _model is None:
        with _model_lock:
            if _model is None:
                from speechbrain.inference.speaker import EncoderClassifier

                savedir = os.path.expanduser("~/.cache/speechbrain/spkrec-ecapa-voxceleb")
                _model = EncoderClassifier.from_hparams(
                    source=HF_MODEL_SOURCE,
                    savedir=savedir,
                    run_opts={"device": "cpu"},
                )
                logger.info("Loaded SpeechBrain ECAPA-TDNN encoder")
    return _model


def compute_voice_embedding(
    audio_path: Path | str, start_ms: int, end_ms: int
) -> list[float]:
    """Extract a 192-d L2-normalized ECAPA embedding from one slice.

    Backward-compatible single-slice helper. For multi-slice accumulation
    (recommended) use ``compute_voice_embedding_spans``.
    """
    duration_ms = end_ms - start_ms
    if duration_ms <= 0:
        raise ValueError(f"Empty snippet range: start_ms={start_ms} end_ms={end_ms}")
    return compute_voice_embedding_spans(audio_path, [(start_ms, end_ms)])


def compute_voice_embedding_spans(
    audio_path: Path | str, spans: list[tuple[int, int]]
) -> list[float]:
    """Decode ``audio_path`` once, concatenate the requested slices, and run
    them through ECAPA-TDNN to produce a single 192-d L2-normalised embedding.

    Multi-span input is the modern enrollment / matching default: pyannote
    and SpeechBrain both report that 20-30s of accumulated same-speaker
    audio (even with intervening other speakers stripped) outperforms a
    single long snippet for impostor robustness.
    """
    import torch
    from pydub import AudioSegment

    if not spans:
        raise ValueError("No spans provided")

    # Decode once. This is O(file) not O(file * n_spans) — the old
    # per-cluster decode pattern blew memory on long meetings.
    full = AudioSegment.from_file(str(audio_path))
    full = full.set_channels(1).set_frame_rate(TARGET_SAMPLE_RATE)

    accumulated = AudioSegment.empty().set_frame_rate(TARGET_SAMPLE_RATE).set_channels(1)
    for start_ms, end_ms in spans:
        if end_ms <= start_ms:
            continue
        accumulated += full[start_ms:end_ms]
    if len(accumulated) == 0:
        raise ValueError("All spans were empty after slicing")

    samples = accumulated.get_array_of_samples()
    max_val = float(1 << (8 * accumulated.sample_width - 1))
    waveform = torch.tensor(samples, dtype=torch.float32).unsqueeze(0) / max_val

    model = _get_model()
    with torch.no_grad():
        embedding = model.encode_batch(waveform).squeeze().cpu()

    normalized = torch.nn.functional.normalize(embedding, dim=0)
    return normalized.tolist()


def pick_clean_snippets(
    results: list["TranscriptResult"],
    raw_label: str,
    target_total_s: float = _MULTI_TOTAL_TARGET_S,
    min_total_s: float = _MULTI_MIN_TOTAL_S,
) -> list[tuple[int, int]] | None:
    """Return up to ``target_total_s`` of contiguous single-speaker spans for
    ``raw_label``, sorted by descending duration.

    Returns ``None`` when the accumulated duration is below ``min_total_s``
    so the caller can fall back to ``raw_label=None`` (unmatched cluster).
    """
    if not results:
        return None

    runs: list[list[int]] = []
    current: list[int] = []
    for idx, tr in enumerate(results):
        if tr.speaker == raw_label:
            current.append(idx)
        else:
            if current:
                runs.append(current)
                current = []
    if current:
        runs.append(current)

    if not runs:
        return None

    spans = [(results[run[0]].start_ms, results[run[-1]].end_ms) for run in runs]
    spans.sort(key=lambda span: span[1] - span[0], reverse=True)

    target_total_ms = int(target_total_s * 1000)
    picked: list[tuple[int, int]] = []
    total_ms = 0
    for start_ms, end_ms in spans:
        if total_ms >= target_total_ms:
            break
        remaining = target_total_ms - total_ms
        duration = end_ms - start_ms
        if duration <= remaining:
            picked.append((start_ms, end_ms))
            total_ms += duration
        else:
            picked.append((start_ms, start_ms + remaining))
            total_ms = target_total_ms
            break

    if total_ms < int(min_total_s * 1000):
        return None
    # Return in transcript order for deterministic concatenation.
    picked.sort(key=lambda span: span[0])
    return picked


def pick_clean_snippet(
    results: list["TranscriptResult"],
    raw_label: str,
    min_s: float = _MIN_SNIPPET_S,
    max_s: float = _MAX_SNIPPET_S,
) -> tuple[int, int] | None:
    """Return ``(start_ms, end_ms)`` of the longest contiguous single-speaker span
    for ``raw_label``, capped at ``max_s``. Returns ``None`` if no span ≥``min_s`` exists.

    Contiguous = consecutive ``TranscriptResult`` entries (by index) all matching
    ``raw_label``; speaker switch breaks the run.
    """
    if not results:
        return None

    runs: list[list[int]] = []
    current: list[int] = []
    for idx, tr in enumerate(results):
        if tr.speaker == raw_label:
            current.append(idx)
        else:
            if current:
                runs.append(current)
                current = []
    if current:
        runs.append(current)

    if not runs:
        return None

    def _duration_ms(run: list[int]) -> int:
        return results[run[-1]].end_ms - results[run[0]].start_ms

    longest = max(runs, key=_duration_ms)
    start_ms = results[longest[0]].start_ms
    end_ms = results[longest[-1]].end_ms

    if end_ms - start_ms < int(min_s * 1000):
        return None

    max_ms = int(max_s * 1000)
    if end_ms - start_ms > max_ms:
        end_ms = start_ms + max_ms

    return start_ms, end_ms
