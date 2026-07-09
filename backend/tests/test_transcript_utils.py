"""Tests for shared transcript helpers."""

from app.core.transcript_utils import TranscriptResult, detect_wav_channels


def test_detect_wav_channels_returns_stereo_when_header_says_two_channels():
    header = bytearray(44)
    header[:4] = b"RIFF"
    header[8:12] = b"WAVE"
    header[22:24] = (2).to_bytes(2, byteorder="little")

    assert detect_wav_channels(bytes(header)) == 2


def test_detect_wav_channels_defaults_to_mono_for_invalid_header():
    assert detect_wav_channels(b"not-a-wav") == 1


def test_transcript_result_keeps_provider_normalized_fields():
    result = TranscriptResult(
        text="Hello",
        speaker="Speaker 1",
        is_final=True,
        start_ms=100,
        end_ms=400,
        confidence=0.9,
    )

    assert result.text == "Hello"
    assert result.speaker == "Speaker 1"
    assert result.is_final is True


def test_resolve_detected_language_pins_unpinned_recordings() -> None:
    from app.core.transcript_utils import resolve_detected_recording_language

    assert (
        resolve_detected_recording_language(
            current="auto", detected="rus", probability=0.99
        )
        == "ru"
    )
    assert (
        resolve_detected_recording_language(
            current="multi", detected="eng", probability=0.8
        )
        == "en"
    )
    assert (
        resolve_detected_recording_language(current=None, detected="ukr", probability=0.9)
        == "uk"
    )
    # Two-letter provider codes pass through.
    assert (
        resolve_detected_recording_language(current="", detected="ru", probability=0.95)
        == "ru"
    )


def test_resolve_detected_language_never_overrides_user_choice() -> None:
    from app.core.transcript_utils import resolve_detected_recording_language

    assert (
        resolve_detected_recording_language(
            current="en", detected="rus", probability=0.99
        )
        is None
    )


def test_resolve_detected_language_requires_confidence_and_known_code() -> None:
    from app.core.transcript_utils import resolve_detected_recording_language

    assert (
        resolve_detected_recording_language(
            current="auto", detected="rus", probability=0.5
        )
        is None
    )
    assert (
        resolve_detected_recording_language(
            current="auto", detected="rus", probability=None
        )
        is None
    )
    assert (
        resolve_detected_recording_language(
            current="auto", detected=None, probability=0.99
        )
        is None
    )
    assert (
        resolve_detected_recording_language(
            current="auto", detected="xxx", probability=0.99
        )
        is None
    )
