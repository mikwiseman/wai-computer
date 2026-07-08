"""Tests for the diarized transcript document renderer."""

from app.core.transcript_document import (
    BLOCK_MAX_CHARS,
    build_transcript_document,
    format_document_timestamp,
    resolve_document_speaker,
)
from app.core.transcript_utils import TranscriptResult


def _tr(
    text: str,
    start_s: float,
    end_s: float,
    *,
    speaker: str | None = "speaker_0",
) -> TranscriptResult:
    return TranscriptResult(
        text=text,
        speaker=speaker,
        is_final=True,
        start_ms=int(start_s * 1000),
        end_ms=int(end_s * 1000),
        confidence=0.95,
    )


def test_format_document_timestamp_is_hh_mm_ss() -> None:
    assert format_document_timestamp(0) == "00:00:00"
    assert format_document_timestamp(18_000) == "00:00:18"
    assert format_document_timestamp(3_722_000) == "01:02:02"
    assert format_document_timestamp(None) == "00:00:00"


def test_resolve_document_speaker_prefers_real_names() -> None:
    names = {"speaker_0": "Дмитрий Рубин"}
    assert resolve_document_speaker("speaker_0", names) == (
        "name:Дмитрий Рубин",
        "Дмитрий Рубин",
        True,
    )
    assert resolve_document_speaker("speaker_1", names) == (
        "speaker:speaker_1",
        "Speaker 2",
        False,
    )
    assert resolve_document_speaker(None, names)[1] == "Speaker"


def test_meeting_renders_timestamped_named_blocks() -> None:
    names = {"speaker_0": "Дмитрий Рубин", "speaker_1": "Мик"}
    doc = build_transcript_document(
        [
            _tr("Так, связь у нас налажена.", 18.0, 27.0, speaker="speaker_0"),
            _tr("Ждём ли мы ещё кого-нибудь?", 27.2, 28.0, speaker="speaker_0"),
            _tr("С нашей стороны нет.", 28.5, 30.0, speaker="speaker_1"),
        ],
        speaker_display_names=names,
    )

    assert doc == (
        "00:00:18 Дмитрий Рубин\n"
        "Так, связь у нас налажена. Ждём ли мы ещё кого-нибудь?\n"
        "\n"
        "00:00:28 Мик\n"
        "С нашей стороны нет.\n"
    )


def test_unnamed_meeting_uses_speaker_numbers() -> None:
    doc = build_transcript_document(
        [
            _tr("Привет.", 0.0, 1.0, speaker="speaker_0"),
            _tr("Привет-привет.", 3.0, 4.0, speaker="speaker_1"),
        ],
        speaker_display_names={},
    )
    assert "00:00:00 Speaker 1\nПривет.\n" in doc
    assert "00:00:03 Speaker 2\nПривет-привет.\n" in doc


def test_monologue_without_name_drops_speaker_line() -> None:
    doc = build_transcript_document(
        [
            _tr("Первая мысль про хакатон.", 0.0, 4.0),
            _tr("Вторая мысль позже.", 40.0, 44.0),
        ],
        speaker_display_names={},
    )
    assert doc == (
        "00:00:00\n"
        "Первая мысль про хакатон.\n"
        "\n"
        "00:00:40\n"
        "Вторая мысль позже.\n"
    )


def test_monologue_with_resolved_name_keeps_name() -> None:
    doc = build_transcript_document(
        [_tr("Заметка на день.", 0.0, 3.0)],
        speaker_display_names={"speaker_0": "Мик"},
    )
    assert doc == "00:00:00 Мик\nЗаметка на день.\n"


def test_long_monologue_splits_into_paragraph_blocks() -> None:
    sentence = "Это довольно длинное предложение про планы и продукт."
    segments = [
        _tr(sentence, float(i * 10), float(i * 10 + 9))
        for i in range(2 * (BLOCK_MAX_CHARS // len(sentence)) + 4)
    ]
    doc = build_transcript_document(segments, speaker_display_names={"speaker_0": "Мик"})

    blocks = doc.strip().split("\n\n")
    assert len(blocks) >= 2
    for block in blocks:
        header, _, body = block.partition("\n")
        assert header.endswith("Мик")
        assert len(body) <= BLOCK_MAX_CHARS + len(sentence) + 1


def test_gap_splits_same_speaker_block() -> None:
    doc = build_transcript_document(
        [
            _tr("До паузы.", 0.0, 2.0),
            _tr("После долгой паузы.", 60.0, 63.0),
        ],
        speaker_display_names={"speaker_0": "Мик"},
    )
    assert doc.count("Мик") == 2
    assert "00:01:00 Мик" in doc


def test_empty_segments_render_empty_document() -> None:
    assert build_transcript_document([], speaker_display_names={}) == ""
    assert (
        build_transcript_document(
            [_tr("   ", 0.0, 1.0)],
            speaker_display_names={},
        )
        == ""
    )
