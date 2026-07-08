"""Diarized transcript document rendering (the attached/downloadable ``.txt``).

Turns provider utterances into the readable meeting-notes layout:

    00:00:18 Дмитрий Рубин
    Так, ну что, связь у нас налажена. По составу команды ждём ли мы ещё
    кого-нибудь?

    00:00:28 Мик
    С нашей стороны нет.

One block per speaker turn. A long monologue is split into paragraph blocks
with fresh timestamps so a ten-minute run doesn't render as one wall of text.
For a single-speaker recording with no resolved real name the speaker line is
dropped and blocks keep timestamps only.
"""

from __future__ import annotations

from app.core.speaker_labels import fallback_speaker_display_name
from app.core.transcript_utils import TranscriptResult, _join_fragments

# A same-speaker run opens a new paragraph block when the accumulated text is
# already long, or after a clear silence gap.
BLOCK_MAX_CHARS = 700
BLOCK_GAP_SPLIT_MS = 15_000

_UNKNOWN_SPEAKER_KEY = "speaker:?"


def format_document_timestamp(ms: int | None) -> str:
    total_seconds = max(0, (ms or 0)) // 1000
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def resolve_document_speaker(
    raw_label: str | None,
    speaker_display_names: dict[str, str],
) -> tuple[str, str, bool]:
    """Return ``(grouping_key, display_label, is_real_name)`` for a segment."""
    label = (raw_label or "").strip()
    if label:
        resolved = (speaker_display_names.get(label) or "").strip()
        if resolved:
            return f"name:{resolved}", resolved, True
        fallback = fallback_speaker_display_name(label)
        if fallback:
            return f"speaker:{label}", fallback, False
        return f"speaker:{label}", label, False
    return _UNKNOWN_SPEAKER_KEY, "Speaker", False


def build_transcript_document(
    transcript_results: list[TranscriptResult],
    *,
    speaker_display_names: dict[str, str] | None = None,
) -> str:
    """Render utterances as timestamped speaker blocks."""
    names = speaker_display_names or {}
    ordered = sorted(transcript_results, key=lambda tr: (tr.start_ms, tr.end_ms))

    blocks: list[tuple[str, str, int, list[str]]] = []  # (key, label, start_ms, texts)
    current: tuple[str, str, int, list[str]] | None = None
    last_end_ms = 0
    real_names_present = False

    for tr in ordered:
        text = tr.text.strip()
        if not text:
            continue
        key, label, is_real = resolve_document_speaker(tr.speaker, names)
        real_names_present = real_names_present or is_real

        if current is not None:
            same_speaker = current[0] == key
            gap_ms = tr.start_ms - last_end_ms
            too_long = len(" ".join(current[3])) >= BLOCK_MAX_CHARS
            if not same_speaker or gap_ms > BLOCK_GAP_SPLIT_MS or too_long:
                blocks.append(current)
                current = None

        if current is None:
            current = (key, label, tr.start_ms, [text])
        else:
            current[3].append(text)
        last_end_ms = max(last_end_ms, tr.end_ms)

    if current is not None:
        blocks.append(current)
    if not blocks:
        return ""

    # A monologue with no real resolved name reads better without a repeated
    # synthetic "Speaker 1" on every block — keep timestamps only.
    distinct_keys = {key for key, _, _, _ in blocks}
    show_speaker = len(distinct_keys) > 1 or real_names_present

    rendered: list[str] = []
    for key, label, start_ms, texts in blocks:
        header = format_document_timestamp(start_ms)
        if show_speaker:
            header = f"{header} {label}"
        body = ""
        for part in texts:
            body = _join_fragments(body, part)
        rendered.append(f"{header}\n{body}")
    return "\n\n".join(rendered) + "\n"
