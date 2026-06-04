"""Shared summary-audio API helper tests."""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi import HTTPException
from starlette.datastructures import Headers

from app.api.summary_audio import (
    _parse_range_header,
    serialize_summary_audio,
    summary_audio_file_response,
)
from app.models.summary_audio import SummaryAudioArtifact, SummaryAudioStatus


def test_serialize_summary_audio_not_started() -> None:
    source_id = uuid4()
    response = serialize_summary_audio(
        source_kind="item",
        source_id=source_id,
        artifact=None,
        audio_url="/api/items/i/summary/audio/file",
    )

    assert response.status == "not_started"
    assert response.audio_url is None
    assert response.source_id == str(source_id)


def test_parse_range_header_supports_prefix_and_suffix() -> None:
    assert _parse_range_header("bytes=0-2", 10) == (0, 2)
    assert _parse_range_header("bytes=5-", 10) == (5, 9)
    assert _parse_range_header("bytes=-3", 10) == (7, 9)

    with pytest.raises(HTTPException) as exc_info:
        _parse_range_header("items=0-1", 10)
    assert exc_info.value.status_code == 416


def test_summary_audio_file_response_rejects_unready_artifact() -> None:
    artifact = SummaryAudioArtifact(
        user_id=uuid4(),
        item_id=uuid4(),
        source_kind="item",
        status=SummaryAudioStatus.QUEUED.value,
        stage="queued",
        progress_percent=5,
        summary_hash="a" * 64,
        input_char_count=1,
        provider="xai",
        model="xai-text-to-speech",
        voice_id="ara",
        language="auto",
    )
    request = type("Request", (), {"headers": Headers({})})()

    with pytest.raises(HTTPException) as exc_info:
        summary_audio_file_response(artifact=artifact, request=request)

    assert exc_info.value.status_code == 409
