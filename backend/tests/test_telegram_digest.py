"""/digest: cross-source period digest (wai-rocks /summary port) — source
collection windows and caps, prompt block, LLM wrapper, and the command flow.
All bot I/O is captured in-memory — zero real network."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes import telegram as telegram_routes
from app.core import telegram_digest
from app.core.telegram_digest import (
    DigestSource,
    build_digest_prompt_block,
    collect_digest_sources,
    digest_period_start,
    generate_telegram_digest,
    parse_digest_days,
)
from app.models.item import Item, ItemSummary
from app.models.recording import Recording, RecordingStatus, Summary
from tests.test_telegram_agent_commands import (  # reuse the shared harness
    _Capture,
    _linked_account,
)

# --- pure helpers ---


def test_parse_digest_days():
    assert parse_digest_days("") == 1
    assert parse_digest_days("  ") == 1
    assert parse_digest_days("3") == 3
    assert parse_digest_days("3 дня") == 3
    assert parse_digest_days("abc") is None
    assert parse_digest_days("0") is None
    assert parse_digest_days("-2") is None


def test_digest_period_start_counts_today_as_day_one():
    now = datetime(2026, 7, 13, 15, 30, tzinfo=timezone.utc)
    assert digest_period_start(1, now=now) == datetime(2026, 7, 13, tzinfo=timezone.utc)
    assert digest_period_start(3, now=now) == datetime(2026, 7, 11, tzinfo=timezone.utc)


def test_build_digest_prompt_block_compact_entries():
    sources = [
        DigestSource(
            kind="встреча",
            title="Планёрка",
            occurred_at=datetime(2026, 7, 13, 10, 0, tzinfo=timezone.utc),
            summary="Обсудили релиз.",
            key_points=["Релиз в пятницу", "Бюджет 100к"],
        )
    ]
    block = build_digest_prompt_block(sources)
    assert "Item 1" in block
    assert "Type: встреча" in block
    assert "Title: Планёрка" in block
    assert "Summary: Обсудили релиз." in block
    assert "KeyPoints: Релиз в пятницу; Бюджет 100к" in block
    assert "2026-07-13 10:00 UTC" in block


# --- collect_digest_sources ---


async def _seed_recording(
    db: AsyncSession,
    user_id,
    *,
    title: str,
    created_at: datetime,
    summary: str | None,
    status: str = RecordingStatus.READY.value,
    rec_type: str = "meeting",
) -> Recording:
    rec = Recording(user_id=user_id, title=title, type=rec_type, status=status)
    db.add(rec)
    await db.flush()
    if summary is not None:
        db.add(
            Summary(
                recording_id=rec.id,
                summary=summary,
                key_points=["точка один"],
            )
        )
    # created_at is server-defaulted; override explicitly for window tests.
    rec.created_at = created_at
    await db.flush()
    return rec


async def _seed_item(
    db: AsyncSession,
    user_id,
    *,
    title: str,
    created_at: datetime,
    summary: str | None,
    body: str | None = None,
    kind: str = "article",
    state: str = "promoted",
) -> Item:
    item = Item(
        user_id=user_id,
        source="telegram",
        kind=kind,
        title=title,
        body=body,
        state=state,
        content_hash=uuid4().hex,
    )
    db.add(item)
    await db.flush()
    if summary is not None:
        db.add(ItemSummary(item_id=item.id, summary=summary, key_points=[]))
    item.created_at = created_at
    await db.flush()
    return item


@pytest.mark.asyncio
async def test_collect_digest_sources_windows_kinds_and_order(db_session, monkeypatch):
    user, _account = await _linked_account(db_session, "tg-digest-1@example.com", 9501)
    now = datetime(2026, 7, 13, 15, 0, tzinfo=timezone.utc)

    await _seed_recording(
        db_session, user.id,
        title="Утренняя планёрка",
        created_at=now - timedelta(hours=3),
        summary="Обсудили запуск.",
    )
    # Outside the 1-day window — excluded.
    await _seed_recording(
        db_session, user.id,
        title="Старая встреча",
        created_at=now - timedelta(days=2),
        summary="Прошлое.",
    )
    # No summary yet — excluded (nothing digestible).
    await _seed_recording(
        db_session, user.id,
        title="Без саммари",
        created_at=now - timedelta(hours=2),
        summary=None,
    )
    await _seed_item(
        db_session, user.id,
        title="Статья про рынок",
        created_at=now - timedelta(hours=1),
        summary="Рынок растёт.",
    )
    # No ItemSummary — falls back to the body head.
    await _seed_item(
        db_session, user.id,
        title="Фото чека",
        created_at=now - timedelta(minutes=30),
        summary=None,
        body="Чек на 1200 рублей за обед.",
        kind="image",
    )
    # Failed item — excluded.
    await _seed_item(
        db_session, user.id,
        title="Битая ссылка",
        created_at=now - timedelta(minutes=10),
        summary=None,
        body=None,
        state="failed",
    )

    sources, total = await collect_digest_sources(db_session, user.id, days=1, now=now)

    assert total == 3
    assert [s.title for s in sources] == [
        "Утренняя планёрка",
        "Статья про рынок",
        "Фото чека",
    ]
    assert [s.kind for s in sources] == ["встреча", "статья", "фото"]
    assert sources[0].key_points == ["точка один"]
    assert "Чек на 1200" in sources[2].summary


@pytest.mark.asyncio
async def test_collect_digest_sources_cap_keeps_newest(db_session, monkeypatch):
    user, _account = await _linked_account(db_session, "tg-digest-2@example.com", 9502)
    now = datetime(2026, 7, 13, 15, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(telegram_digest, "DIGEST_SOURCE_CAP", 2)

    for hour in (5, 4, 3):
        await _seed_item(
            db_session, user.id,
            title=f"Материал -{hour}ч",
            created_at=now - timedelta(hours=hour),
            summary=f"Суть {hour}.",
        )

    sources, total = await collect_digest_sources(db_session, user.id, days=1, now=now)
    assert total == 3
    assert [s.title for s in sources] == ["Материал -4ч", "Материал -3ч"]


# --- generate_telegram_digest ---


def _fake_cerebras(
    monkeypatch,
    *,
    text: str | None = None,
    error: Exception | None = None,
    api_key: str = "k",
):
    monkeypatch.setattr(
        telegram_digest,
        "get_settings",
        lambda: SimpleNamespace(cerebras_api_key=api_key, cerebras_llm_model="gpt-oss-120b"),
    )
    captured: dict[str, Any] = {}

    async def _create(**kwargs):
        captured.update(kwargs)
        if error is not None:
            raise error
        message = SimpleNamespace(content=text)
        choice = SimpleNamespace(message=message, finish_reason="stop")
        return SimpleNamespace(choices=[choice], model="gpt-oss-120b")

    fake_client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=_create))
    )
    monkeypatch.setattr(telegram_digest, "get_cerebras_client", lambda: fake_client)
    return captured


@pytest.mark.asyncio
async def test_generate_telegram_digest_returns_text(monkeypatch):
    captured = _fake_cerebras(monkeypatch, text="Тема:\n- **релиз** `в пятницу`")
    out = await generate_telegram_digest("Item 1\n...", days=1, total_sources=3)
    assert out == "Тема:\n- **релиз** `в пятницу`"
    assert "Materials included: 3" in captured["messages"][1]["content"]


@pytest.mark.asyncio
async def test_generate_telegram_digest_requires_key(monkeypatch):
    _fake_cerebras(monkeypatch, text="x", api_key="")
    with pytest.raises(ValueError):
        await generate_telegram_digest("block", days=1, total_sources=1)


@pytest.mark.asyncio
async def test_generate_telegram_digest_surfaces_failure(monkeypatch):
    _fake_cerebras(monkeypatch, error=RuntimeError("cerebras down"))
    with pytest.raises(RuntimeError):
        await generate_telegram_digest("block", days=1, total_sources=1)


# --- /digest command flow ---


def _stub_digest_pipeline(monkeypatch, *, sources_total=(2, 2), digest="Тема:\n- **пункт**"):
    sources_n, total = sources_total
    sources = [
        DigestSource(
            kind="встреча",
            title=f"Источник {i}",
            occurred_at=datetime(2026, 7, 13, 10 + i, tzinfo=timezone.utc),
            summary="Суть.",
            key_points=[],
        )
        for i in range(sources_n)
    ]

    async def fake_collect(db, user_id, *, days, now=None):
        return sources, total

    async def fake_generate(block, *, days, total_sources):
        return digest

    monkeypatch.setattr(telegram_routes, "collect_digest_sources", fake_collect)
    monkeypatch.setattr(telegram_routes, "generate_telegram_digest", fake_generate)


async def _digest_command(db, capture, account, arg=""):
    await telegram_routes._handle_digest_command(
        db,
        capture,
        message={"message_id": 61, "chat": {"id": 9503}},
        account=account,
        arg=arg,
    )


@pytest.mark.asyncio
async def test_digest_command_replies_with_header_and_html(db_session, monkeypatch):
    _user, account = await _linked_account(db_session, "tg-digest-3@example.com", 9503)
    capture = _Capture()
    _stub_digest_pipeline(monkeypatch)

    await _digest_command(db_session, capture, account)

    assert "Собираю материалы за сегодня" in capture.messages[0]["text"]
    assert {"chat_id": 9503, "message_id": 1} in capture.deleted_messages
    reply = capture.messages[-1]
    assert reply["parse_mode"] == "HTML"
    assert "<b>Дайджест за сегодня</b> · 2 материала" in reply["text"]
    assert "<b>пункт</b>" in reply["text"]


@pytest.mark.asyncio
async def test_digest_command_caps_days_and_discloses_truncation(
    db_session, monkeypatch
):
    _user, account = await _linked_account(db_session, "tg-digest-4@example.com", 9503)
    capture = _Capture()
    _stub_digest_pipeline(monkeypatch, sources_total=(2, 5))

    await _digest_command(db_session, capture, account, arg="30")

    reply = capture.messages[-1]
    assert "Максимум 7 дней" in reply["text"]
    assert "Материалов 5, в дайджест вошли последние 2" in reply["text"]
    assert "за последние 7 дн." in reply["text"]


@pytest.mark.asyncio
async def test_digest_command_empty_period_is_honest(db_session, monkeypatch):
    _user, account = await _linked_account(db_session, "tg-digest-5@example.com", 9503)
    capture = _Capture()

    async def fake_collect(db, user_id, *, days, now=None):
        return [], 0

    monkeypatch.setattr(telegram_routes, "collect_digest_sources", fake_collect)

    await _digest_command(db_session, capture, account)

    assert "Материалов за сегодня пока нет" in capture.messages[-1]["text"]


@pytest.mark.asyncio
async def test_digest_command_generation_failure_is_honest(db_session, monkeypatch):
    _user, account = await _linked_account(db_session, "tg-digest-6@example.com", 9503)
    capture = _Capture()

    async def fake_collect(db, user_id, *, days, now=None):
        return (
            [
                DigestSource(
                    kind="встреча",
                    title="Ист",
                    occurred_at=datetime(2026, 7, 13, tzinfo=timezone.utc),
                    summary="Суть.",
                    key_points=[],
                )
            ],
            1,
        )

    async def fake_generate(block, *, days, total_sources):
        raise RuntimeError("llm down")

    monkeypatch.setattr(telegram_routes, "collect_digest_sources", fake_collect)
    monkeypatch.setattr(telegram_routes, "generate_telegram_digest", fake_generate)

    await _digest_command(db_session, capture, account)

    assert "Дайджест собрать не получилось" in capture.messages[-1]["text"]


@pytest.mark.asyncio
async def test_digest_command_invalid_arg_shows_usage(db_session, monkeypatch):
    _user, account = await _linked_account(db_session, "tg-digest-7@example.com", 9503)
    capture = _Capture()

    await _digest_command(db_session, capture, account, arg="вчера")

    assert "Формат: /digest" in capture.messages[-1]["text"]


def test_digest_text_intent_routes():
    assert telegram_routes._text_intent("дайджест") == ("digest", "")
    assert telegram_routes._text_intent("дайджест за 3 дня") == ("digest", "3")
    assert telegram_routes._text_intent("сделай digest") == ("digest", "")
    long_prose = "мы вчера обсуждали дайджест новостей и решили " + "x" * 60
    assert telegram_routes._text_intent(long_prose) != ("digest", "")


def test_digest_in_help_and_minimal_bot_menu():
    assert "дайджест" in telegram_routes._telegram_help_text(linked=True)
    # The menu is deliberately minimal — everyday actions go through natural
    # language and typed commands share handlers with the NL intents.
    assert [c["command"] for c in telegram_routes.TELEGRAM_BOT_COMMANDS] == ["help"]
    assert json.dumps(telegram_routes.TELEGRAM_BOT_COMMANDS, ensure_ascii=False)
