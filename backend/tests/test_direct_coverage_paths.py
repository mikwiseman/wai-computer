"""Direct unit tests for async route/dependency coverage-critical paths."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException, Response, status
from fastapi.security import HTTPAuthorizationCredentials
from jose import jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import deps
from app.api.routes import action_items, auth, entities, recordings, search, settings
from app.config import get_settings
from app.core.security import (
    create_access_token,
    decode_access_token,
    generate_magic_link_token,
    hash_password,
    verify_password,
)
from app.core.summarizer import SummaryResult
from app.models.entity import EntityRelation
from app.models.recording import ActionItem, Recording, Segment, Summary
from app.models.user import User

settings_obj = get_settings()


async def _create_user(
    db_session: AsyncSession,
    email: str,
    *,
    password_hash_value: str | None = None,
) -> User:
    user = User(email=email, password_hash=password_hash_value)
    db_session.add(user)
    await db_session.flush()
    return user


async def _create_recording(
    db_session: AsyncSession,
    user_id: UUID,
    *,
    title: str | None = "Recording",
    type_: str = "note",
    language: str = "en",
) -> Recording:
    rec = Recording(user_id=user_id, title=title, type=type_, language=language)
    db_session.add(rec)
    await db_session.flush()
    return rec


async def _create_action_item(
    db_session: AsyncSession,
    recording_id: UUID,
    *,
    task: str = "Task",
    status_value: str = "pending",
    priority_value: str = "medium",
    owner: str | None = "Owner",
    due: date | None = date(2026, 3, 1),
    source: str = "generated",
) -> ActionItem:
    item = ActionItem(
        recording_id=recording_id,
        task=task,
        status=status_value,
        priority=priority_value,
        owner=owner,
        due_date=due,
        source=source,
    )
    db_session.add(item)
    await db_session.flush()
    return item


def _dummy_request(cookie_token: str | None = None) -> SimpleNamespace:
    cookies: dict[str, str] = {}
    if cookie_token is not None:
        cookies[settings_obj.auth_cookie_name] = cookie_token
    return SimpleNamespace(cookies=cookies)


def _vector(index: int) -> list[float]:
    values = [0.0] * 384
    values[index] = 1.0
    return values


def _vector_literal(index: int) -> str:
    values = ["0"] * 384
    values[index] = "1"
    return "[" + ",".join(values) + "]"


def _vector_list(index: int) -> list[float]:
    values = [0.0] * 384
    values[index] = 1.0
    return values


@pytest.mark.asyncio
async def test_deps_extract_token_and_optional_user_paths(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="header-token")
    assert deps._extract_access_token(_dummy_request("cookie-token"), credentials) == "header-token"
    assert deps._extract_access_token(_dummy_request("cookie-token"), None) == "cookie-token"
    assert deps._extract_access_token(_dummy_request(None), None) is None

    assert await deps.get_optional_user(_dummy_request(None), None, db_session) is None

    monkeypatch.setattr(deps, "decode_access_token", lambda _: None)
    assert await deps.get_optional_user(_dummy_request("invalid"), None, db_session) is None

    missing_id = uuid4()
    monkeypatch.setattr(deps, "decode_access_token", lambda _: missing_id)
    assert await deps.get_optional_user(_dummy_request("missing"), None, db_session) is None

    user = await _create_user(db_session, "deps.optional@example.com", password_hash_value="hash")
    monkeypatch.setattr(deps, "decode_access_token", lambda _: user.id)
    resolved = await deps.get_optional_user(_dummy_request("valid"), None, db_session)
    assert resolved is not None
    assert resolved.id == user.id


@pytest.mark.asyncio
async def test_deps_get_current_user_error_and_success_paths(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    with pytest.raises(HTTPException) as not_auth:
        await deps.get_current_user(_dummy_request(None), None, db_session)
    assert not_auth.value.status_code == status.HTTP_401_UNAUTHORIZED
    assert "not authenticated" in str(not_auth.value.detail).lower()

    monkeypatch.setattr(deps, "decode_access_token", lambda _: None)
    with pytest.raises(HTTPException) as invalid:
        await deps.get_current_user(_dummy_request("bad"), None, db_session)
    assert invalid.value.status_code == status.HTTP_401_UNAUTHORIZED
    assert "invalid or expired" in str(invalid.value.detail).lower()

    missing_id = uuid4()
    monkeypatch.setattr(deps, "decode_access_token", lambda _: missing_id)
    with pytest.raises(HTTPException) as missing_user:
        await deps.get_current_user(_dummy_request("missing"), None, db_session)
    assert missing_user.value.status_code == status.HTTP_401_UNAUTHORIZED
    assert "user not found" in str(missing_user.value.detail).lower()

    user = await _create_user(db_session, "deps.current@example.com", password_hash_value="hash")
    monkeypatch.setattr(deps, "decode_access_token", lambda _: user.id)
    resolved = await deps.get_current_user(_dummy_request("ok"), None, db_session)
    assert resolved.id == user.id


def test_security_full_path_coverage():
    raw_password = "my-password-123"
    password_hash_value = hash_password(raw_password)
    assert verify_password(raw_password, password_hash_value)
    assert not verify_password("wrong-password", password_hash_value)

    user_id = uuid4()
    default_token = create_access_token(user_id)
    assert decode_access_token(default_token) == user_id

    custom_token = create_access_token(user_id, expires_delta=timedelta(minutes=1))
    assert decode_access_token(custom_token) == user_id

    assert decode_access_token("not-a-token") is None

    no_sub = jwt.encode(
        {"exp": datetime.now(timezone.utc) + timedelta(minutes=1)},
        settings_obj.jwt_secret,
        algorithm=settings_obj.jwt_algorithm,
    )
    assert decode_access_token(no_sub) is None

    bad_sub = jwt.encode(
        {"sub": "not-a-uuid", "exp": datetime.now(timezone.utc) + timedelta(minutes=1)},
        settings_obj.jwt_secret,
        algorithm=settings_obj.jwt_algorithm,
    )
    assert decode_access_token(bad_sub) is None

    token_a = generate_magic_link_token()
    token_b = generate_magic_link_token()
    assert token_a
    assert token_b
    assert token_a != token_b


@pytest.mark.asyncio
async def test_auth_route_direct_paths(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    register_response = Response()
    registered = await auth.register(
        auth.RegisterRequest(email="auth.register@example.com", password="password-123"),
        register_response,
        db_session,
    )
    assert registered.access_token
    assert settings_obj.auth_cookie_name in register_response.headers.get("set-cookie", "")

    with pytest.raises(HTTPException) as duplicate:
        await auth.register(
            auth.RegisterRequest(email="auth.register@example.com", password="password-123"),
            Response(),
            db_session,
        )
    assert duplicate.value.status_code == status.HTTP_400_BAD_REQUEST

    login_response = Response()
    logged_in = await auth.login(
        auth.LoginRequest(email="auth.register@example.com", password="password-123"),
        login_response,
        db_session,
    )
    assert logged_in.access_token
    assert settings_obj.auth_cookie_name in login_response.headers.get("set-cookie", "")

    with pytest.raises(HTTPException) as missing_user:
        await auth.login(
            auth.LoginRequest(email="auth.missing@example.com", password="password-123"),
            Response(),
            db_session,
        )
    assert missing_user.value.status_code == status.HTTP_401_UNAUTHORIZED

    no_password_user = await _create_user(
        db_session,
        "auth.magiconly@example.com",
        password_hash_value=None,
    )
    with pytest.raises(HTTPException) as no_password:
        await auth.login(
            auth.LoginRequest(email=no_password_user.email, password="password-123"),
            Response(),
            db_session,
        )
    assert no_password.value.status_code == status.HTTP_401_UNAUTHORIZED

    with pytest.raises(HTTPException) as wrong_password:
        await auth.login(
            auth.LoginRequest(email="auth.register@example.com", password="wrong"),
            Response(),
            db_session,
        )
    assert wrong_password.value.status_code == status.HTTP_401_UNAUTHORIZED

    sent: list[tuple[str, str]] = []

    async def fake_send_magic_link_email(to_email: str, token: str, **kwargs) -> None:
        sent.append((to_email, token))

    monkeypatch.setattr("app.core.email.send_magic_link_email", fake_send_magic_link_email)

    first_magic = await auth.request_magic_link(
        auth.MagicLinkRequest(email="auth.magic@example.com"),
        db_session,
    )
    second_magic = await auth.request_magic_link(
        auth.MagicLinkRequest(email="auth.magic@example.com"),
        db_session,
    )
    assert first_magic.message
    assert second_magic.message
    assert len(sent) == 2

    with pytest.raises(HTTPException) as invalid_magic:
        await auth.verify_magic_link(
            auth.VerifyMagicLinkRequest(token="invalid-token"),
            Response(),
            db_session,
        )
    assert invalid_magic.value.status_code == status.HTTP_401_UNAUTHORIZED

    expired_user = await _create_user(
        db_session,
        "auth.expired@example.com",
        password_hash_value=None,
    )
    expired_user.magic_link_token = "expired-token"
    expired_user.magic_link_expires = None
    await db_session.flush()

    with pytest.raises(HTTPException) as expired_magic:
        await auth.verify_magic_link(
            auth.VerifyMagicLinkRequest(token="expired-token"),
            Response(),
            db_session,
        )
    assert expired_magic.value.status_code == status.HTTP_401_UNAUTHORIZED

    verify_response = Response()
    verified = await auth.verify_magic_link(
        auth.VerifyMagicLinkRequest(token=sent[-1][1]),
        verify_response,
        db_session,
    )
    assert verified.access_token
    assert settings_obj.auth_cookie_name in verify_response.headers.get("set-cookie", "")

    magic_user_result = await db_session.execute(
        select(User).where(User.email == "auth.magic@example.com")
    )
    magic_user = magic_user_result.scalar_one()
    assert magic_user.magic_link_token is None
    assert magic_user.magic_link_expires is None

    refreshed = await auth.refresh_token(Response(), magic_user)
    assert refreshed.access_token

    logout_response = Response()
    logged_out = await auth.logout(logout_response)
    assert logged_out.message == "Logged out"
    assert settings_obj.auth_cookie_name in logout_response.headers.get("set-cookie", "")

    current_user = await auth.get_current_user_info(magic_user)
    assert current_user.email == "auth.magic@example.com"


@pytest.mark.asyncio
async def test_action_item_route_direct_paths(db_session: AsyncSession):
    user = await _create_user(db_session, "action.direct@example.com", password_hash_value="hash")
    recording = await _create_recording(db_session, user.id)
    item = await _create_action_item(
        db_session,
        recording.id,
        task="Prepare roadmap",
        status_value="pending",
        priority_value="high",
        owner="Alex",
        due=date(2026, 3, 2),
    )

    listed = await action_items.list_action_items(
        user,
        db_session,
        status_filter="pending",
        priority="high",
        limit=20,
        offset=0,
    )
    assert len(listed) == 1
    assert listed[0].id == str(item.id)
    assert listed[0].due_date == "2026-03-02"

    fetched = await action_items.get_action_item(item.id, user, db_session)
    assert fetched.task == "Prepare roadmap"

    with pytest.raises(HTTPException) as missing_get:
        await action_items.get_action_item(uuid4(), user, db_session)
    assert missing_get.value.status_code == status.HTTP_404_NOT_FOUND

    updated = await action_items.update_action_item(
        item.id,
        action_items.UpdateActionItemRequest(
            task="Updated task",
            owner="Taylor",
            due_date="2026-03-10",
            priority="low",
            status="completed",
        ),
        user,
        db_session,
    )
    assert updated.task == "Updated task"
    assert updated.owner == "Taylor"
    assert updated.due_date == "2026-03-10"
    assert updated.priority == "low"
    assert updated.status == "completed"

    cleared = await action_items.update_action_item(
        item.id,
        action_items.UpdateActionItemRequest(owner=None, due_date=""),
        user,
        db_session,
    )
    assert cleared.owner is None
    assert cleared.due_date is None

    with pytest.raises(HTTPException) as invalid_due_date:
        await action_items.update_action_item(
            item.id,
            action_items.UpdateActionItemRequest(due_date="not-a-date"),
            user,
            db_session,
        )
    assert invalid_due_date.value.status_code == status.HTTP_400_BAD_REQUEST

    with pytest.raises(HTTPException) as missing_update:
        await action_items.update_action_item(
            uuid4(),
            action_items.UpdateActionItemRequest(task="x"),
            user,
            db_session,
        )
    assert missing_update.value.status_code == status.HTTP_404_NOT_FOUND

    await action_items.delete_action_item(item.id, user, db_session)

    with pytest.raises(HTTPException) as missing_delete:
        await action_items.delete_action_item(item.id, user, db_session)
    assert missing_delete.value.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.asyncio
async def test_entity_route_direct_paths(db_session: AsyncSession):
    user = await _create_user(db_session, "entity.direct@example.com", password_hash_value="hash")

    created_person = await entities.create_entity(
        entities.CreateEntityRequest(type="person", name="Dana", metadata={"team": "product"}),
        user,
        db_session,
    )
    created_project = await entities.create_entity(
        entities.CreateEntityRequest(type="project", name="Atlas"),
        user,
        db_session,
    )
    assert created_person.name == "Dana"
    assert created_project.type == "project"

    listed_all = await entities.list_entities(user, db_session, type=None, limit=50, offset=0)
    listed_filtered = await entities.list_entities(
        user,
        db_session,
        type="person",
        limit=50,
        offset=0,
    )
    assert len(listed_all) == 2
    assert len(listed_filtered) == 1

    person_id = UUID(created_person.id)
    project_id = UUID(created_project.id)
    db_session.add(
        EntityRelation(
            source_id=person_id,
            target_id=project_id,
            relation_type="works_on",
            context="Sprint planning",
        )
    )
    await db_session.flush()

    detail = await entities.get_entity(person_id, user, db_session)
    assert detail.name == "Dana"
    assert detail.relations[0].target_name == "Atlas"

    with pytest.raises(HTTPException) as missing_get:
        await entities.get_entity(uuid4(), user, db_session)
    assert missing_get.value.status_code == status.HTTP_404_NOT_FOUND

    await entities.delete_entity(person_id, user, db_session)

    with pytest.raises(HTTPException) as missing_delete:
        await entities.delete_entity(person_id, user, db_session)
    assert missing_delete.value.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.asyncio
async def test_recording_route_direct_paths(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    user = await _create_user(
        db_session,
        "recording.direct@example.com",
        password_hash_value="hash",
    )

    created = await recordings.create_recording(
        recordings.CreateRecordingRequest(title="Planning", type="meeting", language="en"),
        user,
        db_session,
    )
    created_note = await recordings.create_recording(
        recordings.CreateRecordingRequest(title=None, type="note", language="en"),
        user,
        db_session,
    )
    assert created.type == "meeting"
    assert created_note.title is None

    listed_all = await recordings.list_recordings(user, db_session, skip=0, limit=50, type=None)
    listed_meeting = await recordings.list_recordings(
        user,
        db_session,
        skip=0,
        limit=50,
        type="meeting",
    )
    assert len(listed_all) == 2
    assert len(listed_meeting) == 1

    first_recording_id = UUID(created.id)
    second_recording_id = UUID(created_note.id)

    with pytest.raises(HTTPException) as missing_detail:
        await recordings.get_recording(uuid4(), user, db_session)
    assert missing_detail.value.status_code == status.HTTP_404_NOT_FOUND

    db_session.add_all(
        [
            Segment(
                recording_id=first_recording_id,
                speaker="Speaker 2",
                content="Second",
                start_ms=2000,
                end_ms=2500,
                confidence=0.9,
            ),
            Segment(
                recording_id=first_recording_id,
                speaker="Speaker 1",
                content="First",
                start_ms=500,
                end_ms=1000,
                confidence=0.95,
            ),
        ]
    )
    db_session.add(
        Summary(
            recording_id=first_recording_id,
            summary="Summary text",
            key_points=["Point"],
            decisions=[{"decision": "Ship"}],
            topics=["topic"],
            people_mentioned=["Sam"],
            sentiment="positive",
        )
    )
    await _create_action_item(
        db_session,
        first_recording_id,
        task="Ship update",
        status_value="pending",
        priority_value="medium",
        owner=None,
        due=None,
    )
    await db_session.flush()

    detail = await recordings.get_recording(first_recording_id, user, db_session)
    assert [segment.content for segment in detail.segments] == ["First", "Second"]
    assert detail.summary is not None
    assert detail.action_items[0].task == "Ship update"

    with pytest.raises(HTTPException) as missing_delete:
        await recordings.delete_recording(uuid4(), user, db_session)
    assert missing_delete.value.status_code == status.HTTP_404_NOT_FOUND

    with pytest.raises(HTTPException) as missing_update:
        await recordings.update_recording(
            uuid4(),
            recordings.UpdateRecordingRequest(title="Nope"),
            user,
            db_session,
        )
    assert missing_update.value.status_code == status.HTTP_404_NOT_FOUND

    updated = await recordings.update_recording(
        first_recording_id,
        recordings.UpdateRecordingRequest(title="Updated Title", type="reflection"),
        user,
        db_session,
    )
    assert updated.title == "Updated Title"
    assert updated.type == "reflection"

    unchanged = await recordings.update_recording(
        first_recording_id,
        recordings.UpdateRecordingRequest(),
        user,
        db_session,
    )
    assert unchanged.title == "Updated Title"
    assert unchanged.type == "reflection"

    with pytest.raises(HTTPException) as missing_transcript:
        await recordings.get_transcript(uuid4(), user, db_session)
    assert missing_transcript.value.status_code == status.HTTP_404_NOT_FOUND

    transcript = await recordings.get_transcript(first_recording_id, user, db_session)
    assert [segment.content for segment in transcript] == ["First", "Second"]

    with pytest.raises(HTTPException) as missing_summary_recording:
        await recordings.get_summary(uuid4(), user, db_session)
    assert missing_summary_recording.value.status_code == status.HTTP_404_NOT_FOUND

    with pytest.raises(HTTPException) as missing_summary_value:
        await recordings.get_summary(second_recording_id, user, db_session)
    assert missing_summary_value.value.status_code == status.HTTP_404_NOT_FOUND

    existing_summary = await recordings.get_summary(first_recording_id, user, db_session)
    assert existing_summary.summary == "Summary text"

    with pytest.raises(HTTPException) as missing_generate:
        await recordings.generate_summary(uuid4(), user, db_session)
    assert missing_generate.value.status_code == status.HTTP_404_NOT_FOUND

    with pytest.raises(HTTPException) as empty_segments:
        await recordings.generate_summary(second_recording_id, user, db_session)
    assert empty_segments.value.status_code == status.HTTP_400_BAD_REQUEST

    generated_recording = await recordings.create_recording(
        recordings.CreateRecordingRequest(title=None, type="note", language="en"),
        user,
        db_session,
    )
    generated_recording_id = UUID(generated_recording.id)

    async def summarize_create(_: str) -> SummaryResult:
        return SummaryResult(
            title="Generated Title",
            summary="Generated summary",
            key_points=["KP1"],
            decisions=[{"decision": "do"}],
            action_items=[
                {
                    "task": "Date object due",
                    "owner": "A",
                    "due": date(2026, 3, 8),
                    "priority": "high",
                },
                {"task": "String due", "owner": "B", "due": "2026-03-09", "priority": "low"},
                {"task": "Bad due", "owner": "C", "due": "bad-date", "priority": "unknown"},
                {"task": "   ", "owner": "D", "due": None, "priority": "medium"},
            ],
            topics=["topic-a"],
            people_mentioned=["A", "B", "C"],
            follow_up_questions=[],
            sentiment="neutral",
        )

    monkeypatch.setattr(recordings, "summarize_transcript", summarize_create)
    db_session.add(
        Segment(
            recording_id=generated_recording_id,
            speaker=None,
            content="Discuss generated summary path.",
            start_ms=0,
            end_ms=900,
            confidence=0.9,
        )
    )
    await db_session.flush()

    generated = await recordings.generate_summary(generated_recording_id, user, db_session)
    assert generated.summary == "Generated summary"

    generated_detail = await recordings.get_recording(generated_recording_id, user, db_session)
    assert generated_detail.title == "Generated Title"
    assert len(generated_detail.action_items) == 3
    assert sorted(item.priority for item in generated_detail.action_items if item.priority) == [
        "high",
        "low",
        "medium",
    ]

    db_session.add(
        ActionItem(
            recording_id=first_recording_id,
            task="Manual task",
            owner="Manual",
            priority="low",
            source="manual",
        )
    )
    db_session.add(
        ActionItem(
            recording_id=first_recording_id,
            task="Old generated task",
            owner=None,
            priority="medium",
            source="generated",
        )
    )
    await db_session.flush()

    async def summarize_update(_: str) -> SummaryResult:
        return SummaryResult(
            title="Should Not Override Title",
            summary="Updated summary",
            key_points=["KP2"],
            decisions=[],
            action_items=[
                {
                    "task": "New generated task",
                    "owner": None,
                    "due": None,
                    "priority": "medium",
                }
            ],
            topics=["topic-b"],
            people_mentioned=[],
            follow_up_questions=[],
            sentiment="positive",
        )

    monkeypatch.setattr(recordings, "summarize_transcript", summarize_update)
    regenerated = await recordings.generate_summary(first_recording_id, user, db_session)
    assert regenerated.summary == "Updated summary"

    regen_detail = await recordings.get_recording(first_recording_id, user, db_session)
    tasks = sorted(item.task for item in regen_detail.action_items)
    assert "Manual task" in tasks
    assert "New generated task" in tasks
    assert "Old generated task" not in tasks
    assert regen_detail.title == "Updated Title"

    await recordings.delete_recording(second_recording_id, user, db_session)


@pytest.mark.asyncio
async def test_search_route_direct_paths(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch):
    user = await _create_user(db_session, "search.direct@example.com", password_hash_value="hash")
    other_user = await _create_user(
        db_session,
        "search.other@example.com",
        password_hash_value="hash",
    )

    user_recording = await _create_recording(db_session, user.id, title="User Search Recording")
    other_recording = await _create_recording(db_session, other_user.id, title="Other Recording")

    db_session.add_all(
        [
            Segment(
                recording_id=user_recording.id,
                speaker="Speaker 1",
                content="Roadmap launch planning",
                start_ms=0,
                end_ms=700,
                confidence=0.95,
                embedding=_vector(0),
            ),
            Segment(
                recording_id=user_recording.id,
                speaker="Speaker 1",
                content="Budget update discussion",
                start_ms=700,
                end_ms=1400,
                confidence=0.9,
                embedding=_vector(1),
            ),
            Segment(
                recording_id=other_recording.id,
                speaker="Speaker 2",
                content="Roadmap launch for another user",
                start_ms=0,
                end_ms=500,
                confidence=0.9,
                embedding=_vector(0),
            ),
        ]
    )
    await db_session.flush()

    async def fake_generate_embedding(_: str) -> list[float]:
        return _vector_list(0)

    monkeypatch.setattr(search, "generate_embedding", fake_generate_embedding)

    hybrid = await search.hybrid_search(user, db_session, q="roadmap", limit=20, offset=0)
    assert hybrid.total >= 1
    assert any("roadmap" in result.content.lower() for result in hybrid.results)
    assert all(result.recording_id != str(other_recording.id) for result in hybrid.results)

    semantic = await search.semantic_search(user, db_session, q="roadmap", limit=20, threshold=0.8)
    assert semantic.total >= 1
    assert any("roadmap" in result.content.lower() for result in semantic.results)

    fts = await search.fulltext_search(user, db_session, q="budget", limit=20, offset=0)
    assert fts.total >= 1
    assert any("budget" in result.content.lower() for result in fts.results)


@pytest.mark.asyncio
async def test_settings_route_direct_paths(db_session: AsyncSession):
    magic_user = await _create_user(
        db_session,
        "settings.magic.direct@example.com",
        password_hash_value=None,
    )
    set_result = await settings.change_password(
        settings.ChangePasswordRequest(current_password="", new_password="magic-new"),
        magic_user,
        db_session,
    )
    assert "set successfully" in set_result.message.lower()

    with pytest.raises(HTTPException) as wrong_current:
        await settings.change_password(
            settings.ChangePasswordRequest(current_password="wrong", new_password="new-pass"),
            magic_user,
            db_session,
        )
    assert wrong_current.value.status_code == status.HTTP_400_BAD_REQUEST

    changed = await settings.change_password(
        settings.ChangePasswordRequest(current_password="magic-new", new_password="rotated-pass"),
        magic_user,
        db_session,
    )
    assert "changed successfully" in changed.message.lower()


@pytest.mark.asyncio
async def test_main_root_health_and_lifespan_paths(monkeypatch: pytest.MonkeyPatch):
    from app import main

    assert await main.root() == {"message": "WaiComputer API", "version": "0.1.0"}

    class DummySession:
        def __init__(self) -> None:
            self.called = False

        async def execute(self, _query) -> None:
            self.called = True

    class DummySessionFactory:
        def __init__(self, session: DummySession) -> None:
            self._session = session

        def __call__(self):
            return self

        async def __aenter__(self) -> DummySession:
            return self._session

        async def __aexit__(self, exc_type, exc, tb) -> bool:
            return False

    session = DummySession()
    monkeypatch.setattr("app.db.session.async_session_maker", DummySessionFactory(session))
    health = await main.health()
    assert health == {"status": "healthy", "database": "connected"}
    assert session.called

    class DummyGenerator:
        def __init__(self) -> None:
            self.loaded = False

        def _load_model(self) -> None:
            self.loaded = True

    generator = DummyGenerator()
    monkeypatch.setattr("app.core.embeddings.get_embedding_generator", lambda: generator)

    async with main.lifespan(main.app):
        assert generator.loaded
