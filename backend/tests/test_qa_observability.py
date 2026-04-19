"""QA pipeline and route observability tests."""

from __future__ import annotations

import logging
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import anthropic
import pytest
from fastapi import HTTPException
from httpx import AsyncClient, Request, Response

from app.api.routes import qa as qa_routes
from app.core import qa as qa_core
from app.core.qa import QAResult, SourceSegment


def test_build_context_text_formats_rows():
    rows = [
        SimpleNamespace(
            recording_title="Weekly Sync",
            speaker="Alice",
            content="Budget was approved.",
        ),
        SimpleNamespace(
            recording_title=None,
            speaker=None,
            content="Timeline remains unchanged.",
        ),
    ]

    context = qa_core.build_context_text(rows)

    assert "[Recording: Weekly Sync] [Alice]: Budget was approved." in context
    assert "[Recording: Untitled] [Unknown]: Timeline remains unchanged." in context


@pytest.mark.asyncio
async def test_retrieve_context_logs_digest_not_raw_question(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
):
    class DummyResult:
        def __init__(self, rows):
            self._rows = rows

        def fetchall(self):
            return self._rows

    rows = [
        SimpleNamespace(
            id=uuid.uuid4(),
            recording_id=uuid.uuid4(),
            recording_title="Hiring Plan",
            speaker="Alice",
            content="We need three engineers.",
            start_ms=0,
            end_ms=1000,
        )
    ]

    class DummyDB:
        async def execute(self, *_args, **_kwargs):
            return DummyResult(rows)

    monkeypatch.setattr(qa_core, "generate_embedding", AsyncMock(return_value=[0.0, 1.0, 2.0]))
    monkeypatch.setattr(qa_core, "format_embedding", lambda _embedding: "[0,1,2]")

    question = "What did alice@example.com say about salaries?"
    caplog.set_level(logging.INFO)
    result = await qa_core.retrieve_context(DummyDB(), uuid.uuid4(), question)

    assert result == rows
    assert question not in caplog.text
    assert "query(len=" in caplog.text
    assert "results=1" in caplog.text


@pytest.mark.asyncio
async def test_ask_database_returns_answer_and_logs_safe_digest(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
):
    source_rows = [
        SimpleNamespace(
            id=uuid.uuid4(),
            recording_id=uuid.uuid4(),
            recording_title="Quarterly Review",
            speaker="Alice",
            content="Budget was approved for hiring.",
            start_ms=1200,
            end_ms=4200,
        )
    ]

    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(
        return_value=SimpleNamespace(
            content=[SimpleNamespace(text="Budget was approved for hiring.")]
        )
    )

    monkeypatch.setattr(qa_core.settings, "anthropic_api_key", "sk-ant-test")
    monkeypatch.setattr(qa_core.settings, "anthropic_model", "claude-sonnet-4")
    monkeypatch.setattr(qa_core, "retrieve_context", AsyncMock(return_value=source_rows))
    monkeypatch.setattr(qa_core, "_get_anthropic_client", lambda: mock_client)

    question = "Did alice@example.com mention compensation?"
    caplog.set_level(logging.INFO)
    result = await qa_core.ask_database(
        db=SimpleNamespace(),
        user_id=uuid.uuid4(),
        question=question,
    )

    assert result.answer == "Budget was approved for hiring."
    assert len(result.source_segments) == 1
    assert result.source_segments[0].speaker == "Alice"
    assert question not in caplog.text
    assert "question(len=" in caplog.text


@pytest.mark.asyncio
async def test_ask_database_maps_rate_limit_to_429(monkeypatch: pytest.MonkeyPatch):
    mock_client = AsyncMock()
    response = Response(429, request=Request("POST", "https://api.anthropic.com/v1/messages"))
    mock_client.messages.create = AsyncMock(
        side_effect=anthropic.RateLimitError("rate limited", response=response, body={})
    )

    monkeypatch.setattr(qa_core.settings, "anthropic_api_key", "sk-ant-test")
    monkeypatch.setattr(qa_core.settings, "anthropic_model", "claude-sonnet-4")
    monkeypatch.setattr(qa_core, "retrieve_context", AsyncMock(return_value=[]))
    monkeypatch.setattr(qa_core, "_get_anthropic_client", lambda: mock_client)

    with pytest.raises(HTTPException) as exc_info:
        await qa_core.ask_database(
            db=SimpleNamespace(),
            user_id=uuid.uuid4(),
            question="What happened?",
        )

    assert exc_info.value.status_code == 429


@pytest.mark.asyncio
async def test_qa_route_uses_safe_breadcrumb_and_log_output(
    client: AsyncClient,
    auth_headers: dict[str, str],
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
):
    breadcrumb_calls: list[dict[str, object]] = []

    def fake_breadcrumb(**kwargs):
        breadcrumb_calls.append(kwargs)

    monkeypatch.setattr(qa_routes, "add_sentry_breadcrumb", fake_breadcrumb)
    monkeypatch.setattr(
        qa_routes,
        "ask_database",
        AsyncMock(
            return_value=QAResult(
                answer="Budget was approved.",
                source_segments=[
                    SourceSegment(
                        segment_id=str(uuid.uuid4()),
                        recording_id=str(uuid.uuid4()),
                        recording_title="Weekly Sync",
                        speaker="Alice",
                        content="Budget was approved.",
                        start_ms=0,
                        end_ms=1000,
                    )
                ],
            )
        ),
    )

    question = "What did alice@example.com say about compensation?"
    caplog.set_level(logging.INFO)
    response = await client.post(
        "/api/qa",
        headers=auth_headers,
        json={"question": question},
    )

    assert response.status_code == 200
    assert response.json()["answer"] == "Budget was approved."
    assert question not in caplog.text
    assert "question_len=" in caplog.text
    assert len(breadcrumb_calls) == 1
    assert breadcrumb_calls[0]["category"] == "qa"
    assert breadcrumb_calls[0]["data"]["query_length"] == len(question)
    assert breadcrumb_calls[0]["data"]["query_hash"] != "-"


@pytest.mark.asyncio
async def test_qa_route_rejects_invalid_recording_uuid(
    client: AsyncClient,
    auth_headers: dict[str, str],
):
    response = await client.post(
        "/api/qa",
        headers=auth_headers,
        json={"question": "What happened?", "recording_ids": ["not-a-uuid"]},
    )

    assert response.status_code == 422
    assert "Invalid UUID" in response.json()["detail"]
