"""Tests for ElevenLabs Scribe pre-recorded (batch) file transcription."""

import math
from unittest.mock import patch

import httpx
import pytest

from app.core.elevenlabs_stt import (
    ELEVENLABS_STT_URL,
    _results_from_scribe_payload,
    apply_transcript_replacements,
    resolve_scribe_language_code,
    sanitize_scribe_keyterms,
    transcribe_audio_file,
)


def _word(
    text: str,
    start: float,
    end: float,
    *,
    speaker: str | None = "speaker_0",
    word_type: str = "word",
    logprob: float | None = None,
) -> dict:
    entry: dict = {"text": text, "start": start, "end": end, "type": word_type}
    if speaker is not None:
        entry["speaker_id"] = speaker
    if logprob is not None:
        entry["logprob"] = logprob
    return entry


def _spacing(start: float, end: float, *, speaker: str | None = "speaker_0") -> dict:
    return _word(" ", start, end, speaker=speaker, word_type="spacing")


def test_resolve_scribe_language_code_maps_auto_and_regional() -> None:
    assert resolve_scribe_language_code("auto") is None
    assert resolve_scribe_language_code("multi") is None
    assert resolve_scribe_language_code(None) is None
    assert resolve_scribe_language_code("") is None
    assert resolve_scribe_language_code("ru") == "ru"
    assert resolve_scribe_language_code("ru-RU") == "ru"
    assert resolve_scribe_language_code("EN") == "en"
    assert resolve_scribe_language_code("weird-value-42") is None


def test_sanitize_scribe_keyterms_dedupes_and_caps() -> None:
    terms = ["WaiComputer", "waicomputer", "  spaced   term  ", "x" * 51, ""]
    sanitized = sanitize_scribe_keyterms(terms)
    assert sanitized == ["WaiComputer", "spaced term"]

    many = [f"term{i}" for i in range(300)]
    assert len(sanitize_scribe_keyterms(many)) == 100


def test_apply_transcript_replacements_is_word_bounded_and_case_insensitive() -> None:
    text = "Позвонить в Гигалам, гигалам ждёт. Мегагигалам не трогаем."
    replaced = apply_transcript_replacements(text, [("гигалам", "GigaLam")])
    assert replaced == "Позвонить в GigaLam, GigaLam ждёт. Мегагигалам не трогаем."


def test_payload_groups_words_into_speaker_segments() -> None:
    payload = {
        "language_code": "ru",
        "words": [
            _word("Привет", 0.0, 0.4, logprob=-0.05),
            _spacing(0.4, 0.41),
            _word("всем.", 0.5, 0.8, logprob=-0.15),
            _word("Привет-привет.", 1.1, 1.6, speaker="speaker_1", logprob=-0.1),
        ],
    }

    results = _results_from_scribe_payload(payload)

    assert [r.text for r in results] == ["Привет всем.", "Привет-привет."]
    assert [r.speaker for r in results] == ["speaker_0", "speaker_1"]
    assert results[0].start_ms == 0
    assert results[0].end_ms == 800
    assert results[1].start_ms == 1100
    expected_confidence = round((math.exp(-0.05) + math.exp(-0.15)) / 2, 4)
    assert results[0].confidence == pytest.approx(expected_confidence)
    assert all(r.is_final for r in results)


def test_payload_splits_same_speaker_on_long_gap() -> None:
    payload = {
        "words": [
            _word("Первая", 0.0, 0.5),
            _spacing(0.5, 0.51),
            _word("мысль.", 0.6, 1.0),
            _word("Вторая", 3.0, 3.5),
            _spacing(3.5, 3.51),
            _word("мысль.", 3.6, 4.0),
        ],
    }

    results = _results_from_scribe_payload(payload)

    assert [r.text for r in results] == ["Первая мысль.", "Вторая мысль."]
    assert results[0].speaker == results[1].speaker == "speaker_0"


def test_payload_splits_monologue_on_sentence_after_soft_duration() -> None:
    words: list[dict] = []
    cursor = 0.0
    for sentence in range(4):
        for token in range(10):
            words.append(_word(f"слово{sentence}_{token}", cursor, cursor + 0.4))
            words.append(_spacing(cursor + 0.4, cursor + 0.41))
            cursor += 0.5
        words[-2]["text"] = words[-2]["text"] + "."
    results = _results_from_scribe_payload({"words": words})

    assert len(results) > 1
    assert all(len(r.text) > 0 for r in results)
    # No content lost or duplicated across the splits.
    rebuilt = " ".join(r.text for r in results).split()
    assert len(rebuilt) == 40


def test_payload_skips_audio_events_and_empty(monkeypatch) -> None:
    payload = {
        "words": [
            _word("(смех)", 0.0, 0.5, word_type="audio_event"),
            _word("Привет.", 0.6, 1.0),
        ],
    }
    results = _results_from_scribe_payload(payload)
    assert [r.text for r in results] == ["Привет."]


def test_payload_missing_words_raises() -> None:
    with pytest.raises(RuntimeError, match="missing words"):
        _results_from_scribe_payload({"text": "hi"})
    with pytest.raises(RuntimeError, match="unexpected payload"):
        _results_from_scribe_payload([1, 2])


@pytest.mark.asyncio
async def test_transcribe_audio_file_posts_multipart_and_parses(monkeypatch) -> None:
    captured: dict = {}

    async def fake_post(self, url, headers=None, data=None, files=None):  # noqa: ANN001
        captured["url"] = url
        captured["headers"] = headers
        captured["data"] = data
        captured["files"] = files
        return httpx.Response(
            200,
            json={
                "language_code": "ru",
                "words": [
                    _word("Готово.", 0.0, 0.5, logprob=-0.02),
                ],
            },
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(
        "app.core.elevenlabs_stt.get_settings",
        lambda: type(
            "S", (), {"elevenlabs_api_key": "sk_test", "elevenlabs_stt_no_verbatim": True}
        )(),
    )
    with patch("httpx.AsyncClient.post", new=fake_post):
        results = await transcribe_audio_file(
            b"audio-bytes",
            language="ru-RU",
            content_type="audio/mpeg",
            keyterms=["WaiComputer", "Сколково"],
            replacements=[("готово", "Готово")],
            audio_duration_seconds=90.0,
        )

    assert captured["url"] == ELEVENLABS_STT_URL
    assert captured["headers"] == {"xi-api-key": "sk_test"}
    fields = captured["data"]
    assert ("model_id", "scribe_v2") in fields
    assert ("diarize", "true") in fields
    assert ("tag_audio_events", "false") in fields
    assert ("no_verbatim", "true") in fields
    assert ("language_code", "ru") in fields
    assert ("keyterms", "WaiComputer") in fields
    assert ("keyterms", "Сколково") in fields
    filename, payload_bytes, content_type = captured["files"]["file"]
    assert filename == "audio.mp3"
    assert payload_bytes == b"audio-bytes"
    assert content_type == "audio/mpeg"
    assert [r.text for r in results] == ["Готово."]


@pytest.mark.asyncio
async def test_transcribe_audio_file_requires_api_key(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.core.elevenlabs_stt.get_settings",
        lambda: type(
            "S", (), {"elevenlabs_api_key": "", "elevenlabs_stt_no_verbatim": True}
        )(),
    )
    with pytest.raises(ValueError, match="ELEVENLABS_API_KEY"):
        await transcribe_audio_file(b"audio", content_type="audio/wav")


@pytest.mark.asyncio
async def test_transcribe_audio_file_raises_on_http_error(monkeypatch) -> None:
    async def fake_post(self, url, headers=None, data=None, files=None):  # noqa: ANN001
        return httpx.Response(422, json={"detail": "bad"}, request=httpx.Request("POST", url))

    monkeypatch.setattr(
        "app.core.elevenlabs_stt.get_settings",
        lambda: type(
            "S", (), {"elevenlabs_api_key": "sk_test", "elevenlabs_stt_no_verbatim": False}
        )(),
    )
    with patch("httpx.AsyncClient.post", new=fake_post):
        with pytest.raises(httpx.HTTPStatusError):
            await transcribe_audio_file(b"audio", content_type="audio/wav")
