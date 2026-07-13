"""Cross-modal voice intent routing: deterministic gate + Cerebras classifier."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.core import telegram_intent
from app.core.telegram_intent import (
    classify_photo_caption,
    classify_voice_transcript,
    route_voice_by_metadata,
)

MAX = 60


def _meta(**kwargs):
    base = dict(
        kind="voice",
        duration_seconds=5.0,
        is_forwarded=False,
        is_reply_to_assistant=False,
        max_command_seconds=MAX,
    )
    base.update(kwargs)
    return route_voice_by_metadata(**base)


def test_non_voice_media_always_files():
    d = _meta(kind="audio")
    assert (d.route, d.reason) == ("file", "non_voice_media")
    assert _meta(kind="video").route == "file"
    assert _meta(kind="video_note").route == "file"
    assert _meta(kind="document").route == "file"


def test_forwarded_voice_files():
    assert _meta(is_forwarded=True) == telegram_intent.VoiceRouteDecision("file", "forwarded")


def test_reply_to_assistant_is_a_message():
    d = _meta(is_reply_to_assistant=True)
    assert (d.route, d.reason) == ("message", "reply_to_assistant")


def test_long_voice_files_without_content():
    d = _meta(duration_seconds=120.0)
    assert (d.route, d.reason) == ("file", "long_form")
    # exactly at the threshold counts as long-form
    assert _meta(duration_seconds=float(MAX)).route == "file"


def test_short_non_forwarded_voice_needs_content():
    # Ambiguous zone: metadata can't decide — caller must transcribe + classify.
    assert _meta(duration_seconds=8.0) is None
    assert _meta(duration_seconds=None) is None


# --- classifier (Cerebras) ---


def _patch_classifier(monkeypatch, *, payload=None, error=None, api_key="k"):
    monkeypatch.setattr(
        telegram_intent,
        "get_settings",
        lambda: SimpleNamespace(cerebras_api_key=api_key, cerebras_llm_model="gpt-oss-120b"),
    )

    async def _create(**_kwargs):
        if error is not None:
            raise error
        message = SimpleNamespace(content=json.dumps(payload))
        choice = SimpleNamespace(message=message, finish_reason="stop")
        return SimpleNamespace(choices=[choice], model="gpt-oss-120b")

    fake_client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=_create))
    )
    monkeypatch.setattr(telegram_intent, "get_cerebras_client", lambda: fake_client)


@pytest.mark.asyncio
async def test_classifier_routes_confident_assistant_to_message(monkeypatch):
    _patch_classifier(
        monkeypatch,
        payload={"target": "assistant", "confidence": "high", "reason": "math question"},
    )
    d = await classify_voice_transcript("сколько будет один плюс два")
    assert d.route == "message"
    assert d.reason == "assistant_high"


@pytest.mark.asyncio
async def test_classifier_files_library_notes(monkeypatch):
    _patch_classifier(
        monkeypatch,
        payload={"target": "library", "confidence": "high", "reason": "self note"},
    )
    d = await classify_voice_transcript("сегодня обсудили роадмап и решили перенести релиз")
    assert d.route == "file"


@pytest.mark.asyncio
async def test_classifier_low_confidence_assistant_defaults_to_file(monkeypatch):
    # Biased to the lossless default: only confident "assistant" becomes a message.
    _patch_classifier(
        monkeypatch,
        payload={"target": "assistant", "confidence": "low", "reason": "unsure"},
    )
    d = await classify_voice_transcript("хм, интересно")
    assert d.route == "file"
    assert d.reason == "assistant_low"


@pytest.mark.asyncio
async def test_empty_transcript_files_without_calling_model(monkeypatch):
    # Would raise if the model were called.
    _patch_classifier(monkeypatch, error=RuntimeError("should not be called"))
    d = await classify_voice_transcript("   ")
    assert (d.route, d.reason) == ("file", "empty_transcript")


@pytest.mark.asyncio
async def test_classifier_error_routes_to_safe_default(monkeypatch):
    _patch_classifier(monkeypatch, error=RuntimeError("cerebras down"))
    d = await classify_voice_transcript("сколько будет один плюс два")
    assert (d.route, d.reason) == ("file", "classifier_error")


@pytest.mark.asyncio
async def test_unconfigured_classifier_files(monkeypatch):
    _patch_classifier(monkeypatch, api_key="")
    d = await classify_voice_transcript("сколько будет один плюс два")
    assert (d.route, d.reason) == ("file", "classifier_unconfigured")


# --- photo caption classifier (Cerebras) ---


@pytest.mark.asyncio
async def test_caption_question_routes_to_answer(monkeypatch):
    _patch_classifier(
        monkeypatch,
        payload={"target": "assistant", "confidence": "high", "reason": "asks translation"},
    )
    d = await classify_photo_caption("переведи этот текст")
    assert (d.route, d.reason) == ("question", "assistant_high")


@pytest.mark.asyncio
async def test_caption_label_routes_to_archive(monkeypatch):
    _patch_classifier(
        monkeypatch,
        payload={"target": "archive", "confidence": "high", "reason": "filing label"},
    )
    d = await classify_photo_caption("чек за обед")
    assert (d.route, d.reason) == ("label", "archive_high")


@pytest.mark.asyncio
async def test_caption_low_confidence_defaults_to_label(monkeypatch):
    _patch_classifier(
        monkeypatch,
        payload={"target": "assistant", "confidence": "low", "reason": "unsure"},
    )
    d = await classify_photo_caption("хм")
    assert (d.route, d.reason) == ("label", "assistant_low")


@pytest.mark.asyncio
async def test_empty_caption_labels_without_calling_model(monkeypatch):
    _patch_classifier(monkeypatch, error=RuntimeError("should not be called"))
    d = await classify_photo_caption("   ")
    assert (d.route, d.reason) == ("label", "empty_caption")


@pytest.mark.asyncio
async def test_caption_classifier_error_defaults_to_label(monkeypatch):
    _patch_classifier(monkeypatch, error=RuntimeError("cerebras down"))
    d = await classify_photo_caption("что это?")
    assert (d.route, d.reason) == ("label", "classifier_error")


@pytest.mark.asyncio
async def test_caption_classifier_unconfigured_defaults_to_label(monkeypatch):
    _patch_classifier(monkeypatch, api_key="")
    d = await classify_photo_caption("что это?")
    assert (d.route, d.reason) == ("label", "classifier_unconfigured")
