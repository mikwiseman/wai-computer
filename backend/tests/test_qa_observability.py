"""Retrieval observability tests.

The legacy /api/qa route + ask_database() were deleted in phase 9. This file
keeps the retrieval coverage that's still load-bearing for the Companion:
build_context_text formatting and retrieve_context's safe-digest logging.
"""

from __future__ import annotations

import logging
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.core import qa as qa_core


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
