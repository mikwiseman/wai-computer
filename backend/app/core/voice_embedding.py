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
    """Extract a 192-d L2-normalized ECAPA embedding from ``audio_path[start_ms:end_ms]``.

    The snippet is resampled to 16 kHz mono if needed. Raises if the slice is empty
    or the audio cannot be decoded.
    """
    import torch
    from pydub import AudioSegment

    duration_ms = end_ms - start_ms
    if duration_ms <= 0:
        raise ValueError(f"Empty snippet range: start_ms={start_ms} end_ms={end_ms}")

    segment = AudioSegment.from_file(str(audio_path))[start_ms:end_ms]
    segment = segment.set_channels(1).set_frame_rate(TARGET_SAMPLE_RATE)

    # AudioSegment → float32 [-1, 1]
    samples = segment.get_array_of_samples()
    max_val = float(1 << (8 * segment.sample_width - 1))
    waveform = torch.tensor(samples, dtype=torch.float32).unsqueeze(0) / max_val

    model = _get_model()
    with torch.no_grad():
        embedding = model.encode_batch(waveform).squeeze().cpu()

    normalized = torch.nn.functional.normalize(embedding, dim=0)
    return normalized.tolist()


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
