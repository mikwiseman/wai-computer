"""Shared transcript models and audio helpers."""

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Literal, Protocol, TypeVar

TranscriptStyle = Literal["plain", "speakers", "timestamped"]

# Closing punctuation that should attach to the previous fragment with no leading
# space when the recogniser splits a clause across consecutive utterances, e.g.
# "сегодняшней" + "сводки." -> "сегодняшней сводки." and "Hello" + ", world".
_CLOSING_PUNCT = ",.;:!?)»”"


@dataclass
class TranscriptResult:
    """Normalized transcript segment returned by speech-to-text providers."""

    text: str
    speaker: str | None
    is_final: bool
    start_ms: int
    end_ms: int
    confidence: float


@dataclass
class TranscriptWord:
    """Word-level unit from the STT provider.

    Kept in memory for processing-time passes (channel merge, echo dedup,
    speaker re-alignment); not persisted today.
    """

    text: str
    speaker: str | None
    start_ms: int
    end_ms: int
    confidence: float | None = None


@dataclass
class FileTranscription:
    """Complete result of one batch file-STT call.

    ``segments`` is the utterance-shaped view every existing consumer uses;
    ``words`` preserves the provider's word stream; ``detected_language`` /
    ``language_probability`` surface the provider's own language detection
    (ISO code as returned by the provider — Scribe uses ISO 639-3).
    """

    segments: list[TranscriptResult]
    words: list[TranscriptWord]
    detected_language: str | None = None
    language_probability: float | None = None


# Provider language detection → app recording language. Scribe reports ISO
# 639-3 codes; the app stores the short subtags the rest of the stack uses
# (settings UI, Deepgram language validation, summary/title prompts).
_ISO_639_3_TO_APP = {
    "rus": "ru",
    "eng": "en",
    "ukr": "uk",
    "bel": "be",
    "deu": "de",
    "ger": "de",
    "fra": "fr",
    "fre": "fr",
    "spa": "es",
    "ita": "it",
    "por": "pt",
    "nld": "nl",
    "dut": "nl",
    "pol": "pl",
    "ces": "cs",
    "cze": "cs",
    "slk": "sk",
    "bul": "bg",
    "srp": "sr",
    "hrv": "hr",
    "bos": "bs",
    "slv": "sl",
    "mkd": "mk",
    "ron": "ro",
    "rum": "ro",
    "hun": "hu",
    "ell": "el",
    "gre": "el",
    "tur": "tr",
    "heb": "he",
    "ara": "ar",
    "hin": "hi",
    "jpn": "ja",
    "kor": "ko",
    "zho": "zh",
    "cmn": "zh",
    "fin": "fi",
    "swe": "sv",
    "nor": "no",
    "nob": "no",
    "dan": "da",
    "est": "et",
    "lav": "lv",
    "lit": "lt",
    "kat": "ka",
    "hye": "hy",
    "kaz": "kk",
    "uzb": "uz",
    "aze": "az",
    "vie": "vi",
    "tha": "th",
    "ind": "id",
    "msa": "ms",
    "may": "ms",
    "fas": "fa",
    "per": "fa",
    "urd": "ur",
    "ben": "bn",
    "tam": "ta",
    "tel": "te",
    "mar": "mr",
    "kan": "kn",
    "tgl": "tl",
    "cat": "ca",
}

# recording.language values that mean "the user did not pin a language".
_UNPINNED_LANGUAGES = {"", "auto", "multi", "und"}

# Below this the provider's guess is too uncertain to pin the recording to a
# single language (heavy code-switching lands here); keep the unpinned value.
DETECTED_LANGUAGE_MIN_PROBABILITY = 0.7


def resolve_detected_recording_language(
    *,
    current: str | None,
    detected: str | None,
    probability: float | None,
) -> str | None:
    """Return the app language code to persist on the recording, or ``None``.

    Only fills in a language when the user left it unpinned (``auto``/``multi``/
    empty), the provider reported one confidently, and the code maps to an app
    subtag. An explicit user choice is never overwritten.
    """
    normalized_current = (current or "").strip().lower()
    if normalized_current not in _UNPINNED_LANGUAGES:
        return None
    if not detected:
        return None
    if probability is None or probability < DETECTED_LANGUAGE_MIN_PROBABILITY:
        return None
    normalized = detected.strip().lower()
    if len(normalized) == 2 and normalized.isalpha():
        return normalized
    return _ISO_639_3_TO_APP.get(normalized)


@dataclass
class TranscriptTurn:
    """Consecutive same-speaker utterances merged into a single speaker turn.

    The recogniser emits short, pause-split utterances; rendering one per line with
    a repeated ``[Speaker, time]`` prefix is unreadable (a monologue gets a label on
    every few words). Merging consecutive same-speaker utterances into turns is the
    single primitive every surface (export, copy, in-app view) builds on.
    """

    key: str
    """Stable grouping identity (``person:<id>`` / ``speaker:<n>`` / raw label / "")."""
    speaker: str
    """Resolved human display label for the turn (e.g. "Speaker 1", "Anna")."""
    start_ms: int | None
    text: str


class _MergeableSegment(Protocol):
    content: str
    start_ms: int | None


_SegT = TypeVar("_SegT", bound=_MergeableSegment)


def _join_fragments(existing: str, addition: str) -> str:
    """Join two utterance fragments with a single space, except before closing punctuation."""
    if not existing:
        return addition
    if not addition:
        return existing
    if addition[0] in _CLOSING_PUNCT:
        return existing + addition
    return existing + " " + addition


def merge_segment_turns(
    segments: Iterable[_SegT],
    *,
    resolve_speaker: Callable[[_SegT], tuple[str, str]],
) -> list[TranscriptTurn]:
    """Merge consecutive segments with the same resolved speaker into turns.

    ``resolve_speaker`` maps a segment to ``(identity_key, display_label)``. The key
    drives grouping (so a turn never splits on a stale label and two different unknown
    speakers never merge); the label is taken from the first segment of each turn.
    Segments are ordered by ``start_ms`` (missing timestamps sort last, stably) and
    empty-content segments are dropped.
    """
    ordered = sorted(segments, key=lambda s: (s.start_ms is None, s.start_ms or 0))
    turns: list[TranscriptTurn] = []
    current: TranscriptTurn | None = None
    for seg in ordered:
        text = (seg.content or "").strip()
        if not text:
            continue
        key, label = resolve_speaker(seg)
        if current is not None and key == current.key:
            current.text = _join_fragments(current.text, text)
        else:
            if current is not None:
                turns.append(current)
            current = TranscriptTurn(key=key, speaker=label, start_ms=seg.start_ms, text=text)
    if current is not None:
        turns.append(current)
    return turns


def render_transcript_turns(
    turns: list[TranscriptTurn],
    *,
    style: TranscriptStyle,
    format_timestamp: Callable[[int | None], str],
) -> str:
    """Render merged turns as a transcript string in the requested style.

    - ``plain``: flowing paragraphs, no timestamps; labels are dropped entirely when
      the whole recording has a single speaker (the "просто текст" case), and lead each
      paragraph otherwise.
    - ``speakers``: like ``plain`` but always shows the speaker label, even for a monologue.
    - ``timestamped``: ``[Speaker, M:SS] text`` per turn, line-joined (today's look, merged).
    """
    if not turns:
        return ""

    if style == "timestamped":
        lines: list[str] = []
        for turn in turns:
            ts = format_timestamp(turn.start_ms)
            if ts:
                lines.append(f"[{turn.speaker}, {ts}] {turn.text}")
            else:
                lines.append(f"[{turn.speaker}] {turn.text}")
        return "\n".join(lines)

    show_labels = style == "speakers" or len({turn.key for turn in turns}) > 1
    paragraphs = [
        f"{turn.speaker}: {turn.text}" if show_labels else turn.text for turn in turns
    ]
    return "\n\n".join(paragraphs)


def detect_wav_channels(audio_data: bytes) -> int:
    """Return the channel count from a WAV header, defaulting to mono."""
    if len(audio_data) < 44:
        return 1
    if audio_data[:4] != b"RIFF" or audio_data[8:12] != b"WAVE":
        return 1
    channels = int.from_bytes(audio_data[22:24], byteorder="little")
    return channels if channels > 0 else 1
