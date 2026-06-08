"""Unit tests for the transcript turn-merging primitive and styled rendering.

These fixtures are the *canonical cross-platform vectors*: the web (TS) and Apple
(Swift) ports assert byte-identical output for the same monologue and dialogue, so
copy/export reads the same on every surface.
"""

from types import SimpleNamespace

from app.core.transcript_utils import (
    TranscriptTurn,
    merge_segment_turns,
    render_transcript_turns,
)


def _seg(speaker: str | None, content: str, start_ms: int | None):
    return SimpleNamespace(speaker=speaker, content=content, start_ms=start_ms)


def _resolve(seg) -> tuple[str, str]:
    """Identity == display label for these tests (label drives nothing in merge)."""
    label = seg.speaker or "Speaker"
    return (seg.speaker or "", label)


def _ts(ms: int | None) -> str:
    if ms is None:
        return ""
    return f"{ms // 60000}:{(ms // 1000) % 60:02d}"


# ---- canonical vectors (mirrored in web + Apple tests) ----

_MONOLOGUE = [
    _seg("speaker_0", "Замечания относительно сегодняшней", 0),
    _seg("speaker_0", "сводки.", 2000),
    _seg("speaker_0", "Я постараюсь подробно объяснить", 4000),
    _seg("speaker_0", "причину своих", 7000),
    _seg("speaker_0", "замечаний,", 9000),
]
_MONOLOGUE_TEXT = (
    "Замечания относительно сегодняшней сводки. "
    "Я постараюсь подробно объяснить причину своих замечаний,"
)

_DIALOGUE = [
    _seg("Speaker 1", "Hello everyone,", 0),
    _seg("Speaker 1", "welcome to the standup.", 3000),
    _seg("Speaker 2", "Thanks for joining.", 15000),
    _seg("Speaker 2", "Let's review the sprint.", 18000),
    _seg("Speaker 1", "I finished the export feature yesterday.", 30000),
]


# ---- merge_segment_turns ----


def test_monologue_collapses_to_single_turn():
    turns = merge_segment_turns(_MONOLOGUE, resolve_speaker=_resolve)
    assert len(turns) == 1
    assert turns[0].text == _MONOLOGUE_TEXT
    assert turns[0].start_ms == 0  # first utterance's start is kept


def test_dialogue_groups_consecutive_same_speaker():
    turns = merge_segment_turns(_DIALOGUE, resolve_speaker=_resolve)
    assert [t.speaker for t in turns] == ["Speaker 1", "Speaker 2", "Speaker 1"]
    assert turns[0].text == "Hello everyone, welcome to the standup."
    assert turns[1].text == "Thanks for joining. Let's review the sprint."
    assert turns[2].text == "I finished the export feature yesterday."


def test_merge_orders_by_start_ms():
    turns = merge_segment_turns(
        [_seg("A", "second", 1000), _seg("A", "first", 0)],
        resolve_speaker=_resolve,
    )
    assert turns[0].text == "first second"


def test_merge_skips_empty_and_whitespace_segments():
    turns = merge_segment_turns(
        [_seg("A", "  ", 0), _seg("A", "real", 1000), _seg("A", "", 2000)],
        resolve_speaker=_resolve,
    )
    assert len(turns) == 1
    assert turns[0].text == "real"


def test_null_speaker_bucket_does_not_merge_with_labelled_speaker():
    turns = merge_segment_turns(
        [_seg(None, "anon", 0), _seg("speaker_0", "named", 1000)],
        resolve_speaker=_resolve,
    )
    assert [t.key for t in turns] == ["", "speaker_0"]


def test_null_timestamps_sort_last():
    turns = merge_segment_turns(
        [_seg("A", "no-ts", None), _seg("B", "has-ts", 5000)],
        resolve_speaker=_resolve,
    )
    # The timestamped segment sorts before the None-timestamp one despite input order.
    assert [t.text for t in turns] == ["has-ts", "no-ts"]


def test_join_does_not_space_before_closing_punctuation():
    turns = merge_segment_turns(
        [_seg("A", "Hello", 0), _seg("A", ", world", 1000)],
        resolve_speaker=_resolve,
    )
    assert turns[0].text == "Hello, world"


# ---- render_transcript_turns ----


def test_render_plain_monologue_drops_labels():
    turns = merge_segment_turns(_MONOLOGUE, resolve_speaker=_resolve)
    rendered = render_transcript_turns(turns, style="plain", format_timestamp=_ts)
    assert rendered == _MONOLOGUE_TEXT  # no "Speaker", no timestamps


def test_render_plain_dialogue_leads_each_paragraph_with_label():
    turns = merge_segment_turns(_DIALOGUE, resolve_speaker=_resolve)
    rendered = render_transcript_turns(turns, style="plain", format_timestamp=_ts)
    assert rendered == (
        "Speaker 1: Hello everyone, welcome to the standup.\n\n"
        "Speaker 2: Thanks for joining. Let's review the sprint.\n\n"
        "Speaker 1: I finished the export feature yesterday."
    )


def test_render_speakers_style_labels_even_a_monologue():
    turns = merge_segment_turns(_MONOLOGUE, resolve_speaker=_resolve)
    rendered = render_transcript_turns(turns, style="speakers", format_timestamp=_ts)
    # The pure primitive shows whatever label `resolve_speaker` returns (raw here);
    # backend/web/Apple supply humanised labels ("Speaker 1") via their own resolvers.
    assert rendered == f"speaker_0: {_MONOLOGUE_TEXT}"


def test_render_timestamped_merges_into_one_line_per_turn():
    turns = merge_segment_turns(_DIALOGUE, resolve_speaker=_resolve)
    rendered = render_transcript_turns(turns, style="timestamped", format_timestamp=_ts)
    assert rendered == (
        "[Speaker 1, 0:00] Hello everyone, welcome to the standup.\n"
        "[Speaker 2, 0:15] Thanks for joining. Let's review the sprint.\n"
        "[Speaker 1, 0:30] I finished the export feature yesterday."
    )


def test_render_timestamped_omits_timestamp_when_missing():
    turns = [TranscriptTurn(key="speaker_0", speaker="Speaker 1", start_ms=None, text="hi")]
    rendered = render_transcript_turns(turns, style="timestamped", format_timestamp=_ts)
    assert rendered == "[Speaker 1] hi"


def test_render_empty_turns_returns_empty_string():
    assert render_transcript_turns([], style="plain", format_timestamp=_ts) == ""
