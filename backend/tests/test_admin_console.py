"""Admin console API tests."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes import admin as admin_routes
from app.api.routes.admin import AdminPromoCodeCreateRequest
from app.billing.promo_codes import hash_promo_code
from app.models.admin import AdminRole, StaffMember
from app.models.ai_usage import AiUsageEvent
from app.models.api_key import ApiKey
from app.models.billing import (
    BillingEvent,
    BillingPromoCode,
    BillingPromoRedemption,
    Invoice,
    Plan,
    Subscription,
    UsageWeek,
)
from app.models.companion import ChatMessage, Conversation
from app.models.deepgram_usage import DeepgramUsageEvent
from app.models.dictation import DictationEntry
from app.models.recording import Recording, Segment
from app.models.refresh_token import RefreshToken
from app.models.user import User

LEGAL_ACCEPTANCE = {
    "accepted_legal_terms": True,
    "legal_terms_version": "2026-05-22",
    "legal_privacy_version": "2026-05-22",
}


async def _register(client: AsyncClient, email: str) -> tuple[dict, dict]:
    response = await client.post(
        "/api/auth/register",
        json={"email": email, "password": "testpassword123", **LEGAL_ACCEPTANCE},
    )
    assert response.status_code == 200
    payload = response.json()
    headers = {"Authorization": f"Bearer {payload['access_token']}"}
    me = await client.get("/api/auth/me", headers=headers)
    assert me.status_code == 200
    payload["user_id"] = me.json()["id"]
    return payload, headers


async def _grant_admin(db: AsyncSession, user_id, role: str = "owner") -> None:
    staff_member = (
        await db.execute(select(StaffMember).where(StaffMember.user_id == user_id))
    ).scalar_one_or_none()
    if staff_member is None:
        staff_member = StaffMember(user_id=user_id, status="active")
        db.add(staff_member)
        await db.flush()
    db.add(AdminRole(staff_member_id=staff_member.id, role=role))
    await db.flush()


@pytest.mark.asyncio
async def test_admin_routes_require_admin_role(
    client: AsyncClient,
    db_session: AsyncSession,
):
    _, user_headers = await _register(client, "ordinary-admin-check@example.com")

    forbidden = await client.get("/api/admin/stats", headers=user_headers)
    client.cookies.clear()
    anonymous = await client.get("/api/admin/stats")

    assert forbidden.status_code == 403
    assert forbidden.json()["detail"] == "Admin role required"
    assert anonymous.status_code in {401, 403}


@pytest.mark.asyncio
async def test_admin_principal_allows_multiple_staff_roles(
    client: AsyncClient,
    db_session: AsyncSession,
):
    admin_payload, admin_headers = await _register(client, "admin-multi-role@example.com")
    await _grant_admin(db_session, admin_payload["user_id"], role="support")
    await _grant_admin(db_session, admin_payload["user_id"], role="owner")

    response = await client.get("/api/admin/stats", headers=admin_headers)

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_admin_ai_usage_rows_aggregate_filter_and_analyze(
    db_session: AsyncSession,
):
    now = datetime.now(timezone.utc)
    power_user = User(email="ai-usage-power@example.com", password_hash="x")
    other_user = User(email="ai-usage-other@example.com", password_hash="x")
    db_session.add_all([power_user, other_user])
    await db_session.flush()

    db_session.add_all(
        [
            AiUsageEvent(
                created_at=now - timedelta(minutes=6),
                user_id=power_user.id,
                provider="openai",
                feature="embeddings",
                operation="embedding.batch",
                status="succeeded",
                model="text-embedding-3-large",
                input_tokens=4_000,
                output_tokens=0,
                cached_tokens=50,
                reasoning_tokens=0,
                total_tokens=4_000,
                latency_ms=20,
                estimated_cost_usd=2.0,
                pricing_status="priced",
                price_source="openai-api-pricing-2026-06-04",
                request_id="req-ai-usage-1",
            ),
            AiUsageEvent(
                created_at=now - timedelta(minutes=5),
                user_id=power_user.id,
                provider="openai",
                feature="embeddings",
                operation="embedding.single",
                status="succeeded",
                model="text-embedding-3-large",
                input_tokens=3_500,
                output_tokens=0,
                cached_tokens=25,
                reasoning_tokens=0,
                total_tokens=3_500,
                latency_ms=35,
                estimated_cost_usd=1.5,
                pricing_status="priced",
                price_source="openai-api-pricing-2026-06-04",
                request_id="req-ai-usage-2",
            ),
            AiUsageEvent(
                created_at=now - timedelta(minutes=4),
                user_id=power_user.id,
                provider="openai",
                feature="embeddings",
                operation="embedding.batch",
                status="failed",
                model="gpt-unpriced",
                input_tokens=1_000,
                output_tokens=0,
                cached_tokens=0,
                reasoning_tokens=0,
                total_tokens=1_000,
                latency_ms=80,
                estimated_cost_usd=0.0,
                pricing_status="unpriced",
                provider_status_code=429,
                provider_error_code="rate_limit",
                error_type="ProviderRateLimit",
            ),
            AiUsageEvent(
                created_at=now - timedelta(minutes=3),
                user_id=power_user.id,
                provider="openai",
                feature="companion",
                operation="chat.answer",
                status="refused",
                model="gpt-unpriced",
                input_tokens=300,
                output_tokens=50,
                cached_tokens=0,
                reasoning_tokens=10,
                total_tokens=350,
                latency_ms=120,
                estimated_cost_usd=0.0,
                pricing_status="unpriced",
                guard_code="private_content",
                error_type="GuardRefusal",
            ),
            AiUsageEvent(
                created_at=now - timedelta(minutes=2),
                user_id=other_user.id,
                provider="deepgram",
                feature="transcription",
                operation="recording.transcribe",
                status="failed",
                model="nova-3",
                billable_seconds=60,
                audio_seconds=57.2,
                latency_ms=250,
                estimated_cost_usd=0.0058,
                pricing_status="priced",
                billing_mode="pre_recorded",
                language_mode="multilingual",
                addons=["speaker_diarization"],
                provider_status_code=402,
                provider_error_code="insufficient_credit",
            ),
            AiUsageEvent(
                created_at=now - timedelta(minutes=1),
                user_id=None,
                provider="openai",
                feature="embeddings",
                operation="embedding.query",
                status="succeeded",
                model="text-embedding-3-large",
                input_tokens=200,
                output_tokens=0,
                cached_tokens=0,
                reasoning_tokens=0,
                total_tokens=200,
                latency_ms=10,
                estimated_cost_usd=0.05,
                pricing_status="priced",
            ),
        ]
    )
    await db_session.flush()

    payload = await admin_routes._ai_usage_rows(
        db_session,
        since=now - timedelta(days=1),
        detail_limit=10,
    )

    assert payload["summary"] == {
        "events": 6,
        "estimated_cost_usd": 3.5558,
        "input_tokens": 9_000,
        "output_tokens": 50,
        "cached_tokens": 75,
        "reasoning_tokens": 10,
        "total_tokens": 9_050,
        "billable_seconds": 60.0,
        "audio_seconds": 57.2,
        "failed_events": 2,
        "refused_events": 1,
        "unpriced_events": 2,
        "avg_latency_ms": 86,
        "p95_latency_ms": 250,
    }
    assert payload["by_day"] == [
        {
            "date": now.date().isoformat(),
            "events": 6,
            "estimated_cost_usd": 3.5558,
            "total_tokens": 9_050,
            "billable_seconds": 60.0,
            "failed_events": 2,
            "refused_events": 1,
        }
    ]
    assert {row["provider"] for row in payload["by_provider"]} == {"openai", "deepgram"}
    assert payload["by_user"][0]["email"] == "ai-usage-power@example.com"
    assert any(row["user_id"] == "unknown" for row in payload["by_user"])
    assert payload["recent_events"][0]["operation"] == "embedding.query"
    assert payload["recent_events"][1]["addons"] == ["speaker_diarization"]

    codes = {item["code"] for item in admin_routes._ai_usage_analysis(payload)}
    assert {
        "ai_usage.unpriced_models",
        "ai_usage.failure_ratio.high",
        "ai_usage.cost.concentrated_user",
        "ai_usage.tokens.concentrated_feature",
        "ai_usage.provider.openai.errors",
        "ai_usage.provider.deepgram.errors",
    } <= codes

    filtered = await admin_routes._ai_usage_rows(
        db_session,
        since=now - timedelta(days=1),
        detail_limit=10,
        provider="openai",
        feature="embeddings",
        model="text-embedding-3-large",
        status_filter="succeeded",
        user_id=power_user.id,
        q="power@example.com",
    )

    assert filtered["summary"]["events"] == 2
    assert filtered["summary"]["estimated_cost_usd"] == 3.5
    assert {row["model"] for row in filtered["by_model"]} == {"text-embedding-3-large"}
    assert {event["email"] for event in filtered["recent_events"]} == {
        "ai-usage-power@example.com"
    }

    empty = await admin_routes._ai_usage_rows(
        db_session,
        since=now + timedelta(days=1),
        detail_limit=10,
    )

    assert empty["summary"]["events"] == 0
    assert empty["summary"]["p95_latency_ms"] is None
    assert admin_routes._ai_usage_analysis(empty)[0]["code"] == "ai_usage.ledger.empty"


@pytest.mark.asyncio
async def test_admin_deepgram_usage_rows_combine_ledger_estimates_and_analyze(
    db_session: AsyncSession,
):
    now = datetime.now(timezone.utc)
    power_user = User(email="deepgram-power@example.com", password_hash="x")
    other_user = User(email="deepgram-other@example.com", password_hash="x")
    db_session.add_all([power_user, other_user])
    await db_session.flush()

    long_recording = Recording(
        user_id=power_user.id,
        title="Long captured meeting",
        type="meeting",
        status="ready",
        created_at=now - timedelta(minutes=8),
        uploaded_at=now - timedelta(minutes=7),
        duration_seconds=120,
        billed_word_count=1_000,
    )
    failed_recording = Recording(
        user_id=power_user.id,
        title="Failed provider meeting",
        type="meeting",
        status="failed",
        failure_code="deepgram_payment_required",
        created_at=now - timedelta(minutes=7),
        uploaded_at=now - timedelta(minutes=6),
        duration_seconds=45,
        billed_word_count=120,
    )
    other_recording = Recording(
        user_id=other_user.id,
        title="Short recording",
        type="meeting",
        status="ready",
        created_at=now - timedelta(minutes=6),
        uploaded_at=now - timedelta(minutes=5),
        duration_seconds=20,
        billed_word_count=80,
    )
    db_session.add_all([long_recording, failed_recording, other_recording])
    await db_session.flush()

    db_session.add_all(
        [
            DictationEntry(
                user_id=power_user.id,
                client_entry_id=uuid4(),
                raw_text="hello wai",
                cleaned_text="Hello Wai.",
                duration_seconds=15.5,
                word_count=30,
                occurred_at=now - timedelta(minutes=4),
            ),
            DictationEntry(
                user_id=other_user.id,
                client_entry_id=uuid4(),
                raw_text="short note",
                cleaned_text="Short note.",
                duration_seconds=5.0,
                word_count=10,
                occurred_at=now - timedelta(minutes=3),
            ),
            DeepgramUsageEvent(
                created_at=now - timedelta(minutes=6),
                user_id=power_user.id,
                recording_id=long_recording.id,
                operation="file_stt",
                purpose="recording",
                status="succeeded",
                model="nova-3",
                language="ru",
                content_type="audio/mp4",
                audio_seconds=120,
                billable_seconds=120,
                channel_count=1,
                audio_bytes=1_200_000,
                latency_ms=900,
                estimated_cost_usd=0.0116,
                pricing_status="priced",
                billing_mode="pre_recorded",
                language_mode="multilingual",
                addons=["speaker_diarization"],
                price_source="deepgram-payg-2026-06-04",
            ),
            DeepgramUsageEvent(
                created_at=now - timedelta(minutes=5),
                user_id=power_user.id,
                recording_id=long_recording.id,
                operation="file_stt",
                purpose="recording",
                status="failed",
                model="nova-3",
                language="ru",
                content_type="audio/mp4",
                audio_seconds=120,
                billable_seconds=120,
                channel_count=1,
                audio_bytes=1_200_000,
                latency_ms=1_100,
                estimated_cost_usd=0.0,
                pricing_status="unpriced",
                billing_mode="pre_recorded",
                language_mode="multilingual",
                provider_status_code=402,
                provider_error_code="payment_required",
                error_type="DeepgramPaymentRequired",
            ),
            DeepgramUsageEvent(
                created_at=now - timedelta(minutes=4),
                user_id=power_user.id,
                operation="realtime_stream",
                purpose="dictation",
                status="refused",
                model="nova-3",
                language="en",
                content_type="audio/raw",
                audio_seconds=15.5,
                billable_seconds=0,
                latency_ms=45,
                estimated_cost_usd=0.0,
                pricing_status="unpriced",
                guard_code="silent_audio",
                error_type="GuardRefusal",
            ),
            DeepgramUsageEvent(
                created_at=now - timedelta(minutes=3),
                user_id=other_user.id,
                operation="realtime_stream",
                purpose="dictation",
                status="succeeded",
                model="nova-3",
                language="en",
                content_type="audio/raw",
                audio_seconds=5,
                billable_seconds=5,
                channel_count=1,
                audio_bytes=80_000,
                latency_ms=180,
                estimated_cost_usd=0.00048,
                pricing_status="priced",
                billing_mode="streaming",
                language_mode="monolingual",
            ),
        ]
    )
    await db_session.flush()

    payload = await admin_routes._deepgram_usage_rows(
        db_session,
        since=now - timedelta(days=1),
        detail_limit=10,
    )

    assert payload["captured"] == {
        "events": 4,
        "estimated_cost_usd": 0.01208,
        "audio_seconds": 260.5,
        "billable_seconds": 245.0,
        "succeeded": 2,
        "failed": 1,
        "refused": 1,
        "provider_402": 1,
        "unpriced_events": 2,
    }
    assert payload["estimated"] == {
        "recording_seconds": 185.0,
        "recording_words": 1_200,
        "recording_count": 3,
        "failed_recordings": 1,
        "dictation_seconds": 20.5,
        "dictation_words": 40,
        "dictation_entries": 2,
        "total_seconds": 205.5,
    }
    assert payload["by_user"][0]["email"] == "deepgram-power@example.com"
    assert payload["by_user"][0]["captured_events"] == 3
    assert payload["by_user"][0]["estimated_total_seconds"] == 180.5
    assert {row["operation"] for row in payload["by_operation"]} == {
        "file_stt",
        "realtime_stream",
    }
    assert payload["by_day"] == [
        {
            "date": now.date().isoformat(),
            "captured_events": 4,
            "captured_audio_seconds": 260.5,
            "captured_estimated_cost_usd": 0.01208,
            "captured_billable_seconds": 245.0,
            "captured_failed_events": 1,
            "captured_refused_events": 1,
            "captured_unpriced_events": 2,
            "estimated_recordings": 3,
            "estimated_recording_seconds": 185.0,
            "estimated_dictation_entries": 2,
            "estimated_dictation_seconds": 20.5,
        }
    ]
    assert payload["top_recordings"][0]["recording_id"] == str(long_recording.id)
    assert payload["top_recordings"][0]["captured_events"] == 2
    assert payload["top_recordings"][0]["failed_events"] == 1
    assert payload["top_recordings"][0]["provider_402_events"] == 1
    assert payload["recent_events"][0]["operation"] == "realtime_stream"
    assert payload["recent_events"][0]["email"] == "deepgram-other@example.com"

    codes = {item["code"] for item in admin_routes._deepgram_usage_analysis(payload)}
    assert {
        "deepgram.pricing.partial",
        "deepgram.provider.payment_required",
        "deepgram.guard.refused",
        "deepgram.provider.failed",
        "deepgram.usage.concentrated_user",
        "deepgram.recording.repeated_attempts",
        "deepgram.recordings.failed",
    } <= codes

    empty = await admin_routes._deepgram_usage_rows(
        db_session,
        since=now + timedelta(days=1),
        detail_limit=10,
    )
    assert empty["captured"]["events"] == 0
    assert admin_routes._deepgram_usage_analysis(empty)[0]["code"] == "deepgram.ledger.empty"


@pytest.mark.asyncio
async def test_admin_can_manage_promo_codes_and_see_redemption_stats(
    client: AsyncClient,
    db_session: AsyncSession,
):
    admin_payload, admin_headers = await _register(client, "admin-promos@example.com")
    user_payload, _ = await _register(client, "promo-user@example.com")
    await _grant_admin(db_session, admin_payload["user_id"])

    create = await client.post(
        "/api/admin/promo-codes",
        headers=admin_headers,
        json={
            "code": "WAI-ADMIN-CONSOLE",
            "duration_days": 30,
            "max_redemptions": 10,
            "expires_days": 60,
            "note": "console test",
        },
    )
    assert create.status_code == 200
    promo_id = create.json()["id"]
    assert create.json()["code"] == "WAI-ADMIN-CONSOLE"

    promo = (
        await db_session.execute(
            select(BillingPromoCode).where(
                BillingPromoCode.code_hash == hash_promo_code("WAI-ADMIN-CONSOLE")
            )
        )
    ).scalar_one()
    plan = (await db_session.execute(select(Plan).where(Plan.code == "pro"))).scalar_one()
    sub = Subscription(
        user_id=user_payload["user_id"],
        plan_id=plan.id,
        status="active",
        provider="promo",
        billing_period="month",
        current_period_start=datetime.now(timezone.utc),
        current_period_end=datetime.now(timezone.utc) + timedelta(days=30),
    )
    db_session.add(sub)
    await db_session.flush()
    db_session.add(
        BillingPromoRedemption(
            promo_code_id=promo.id,
            user_id=user_payload["user_id"],
            subscription_id=sub.id,
        )
    )
    promo.redeemed_count = 1
    await db_session.flush()

    listed = await client.get("/api/admin/promo-codes", headers=admin_headers)
    assert listed.status_code == 200
    item = listed.json()["items"][0]
    assert item["id"] == promo_id
    assert item["redemption_rate"] == 0.1
    assert item["redemptions"][0]["user_email"] == "promo-user@example.com"
    assert item["code"] == "WAI-ADMIN-CONSOLE"

    patched = await client.patch(
        f"/api/admin/promo-codes/{promo_id}",
        headers=admin_headers,
        json={"active": False, "note": "paused test", "max_redemptions": 25},
    )
    assert patched.status_code == 200
    assert patched.json()["active"] is False
    assert patched.json()["note"] == "paused test"
    assert patched.json()["max_redemptions"] == 25

    archived = await client.delete(f"/api/admin/promo-codes/{promo_id}", headers=admin_headers)
    archived_patch = await client.patch(
        f"/api/admin/promo-codes/{promo_id}",
        headers=admin_headers,
        json={"active": True},
    )
    archived_delete = await client.delete(
        f"/api/admin/promo-codes/{promo_id}", headers=admin_headers
    )
    assert archived.status_code == 204
    assert archived_patch.status_code == 404
    assert archived_delete.status_code == 404
    await db_session.refresh(promo)
    assert promo.archived_at is not None


def test_admin_promo_code_create_request_normalizes_operator_input():
    payload = AdminPromoCodeCreateRequest(
        code="   ",
        prefix=" support ",
        duration_days=7,
        max_redemptions=1,
        note="  created by support  ",
    )

    assert payload.code is None
    assert payload.prefix == "SUPPORT"
    assert payload.note == "created by support"


@pytest.mark.asyncio
async def test_admin_promo_code_validation_and_error_paths(
    client: AsyncClient,
    db_session: AsyncSession,
):
    admin_payload, admin_headers = await _register(client, "admin-promo-errors@example.com")
    await _grant_admin(db_session, admin_payload["user_id"])

    missing_plan = await client.post(
        "/api/admin/promo-codes",
        headers=admin_headers,
        json={
            "code": "WAI-MISSING-PLAN",
            "plan": "missing",
            "duration_days": 30,
            "max_redemptions": 10,
        },
    )
    invalid_prefix = await client.post(
        "/api/admin/promo-codes",
        headers=admin_headers,
        json={"prefix": "***", "duration_days": 30, "max_redemptions": 10},
    )
    invalid_code = await client.post(
        "/api/admin/promo-codes",
        headers=admin_headers,
        json={"code": "***", "duration_days": 30, "max_redemptions": 10},
    )
    auto_created = await client.post(
        "/api/admin/promo-codes",
        headers=admin_headers,
        json={
            "code": "",
            "prefix": "SUPPORT",
            "duration_days": 7,
            "max_redemptions": 1,
            "expires_days": None,
            "note": "   ",
        },
    )
    created = await client.post(
        "/api/admin/promo-codes",
        headers=admin_headers,
        json={
            "code": "WAI-DUPLICATE",
            "duration_days": 30,
            "max_redemptions": 5,
            "note": "  duplicate test  ",
        },
    )
    duplicate = await client.post(
        "/api/admin/promo-codes",
        headers=admin_headers,
        json={"code": "WAI-DUPLICATE", "duration_days": 30, "max_redemptions": 5},
    )
    promo = (
        await db_session.execute(
            select(BillingPromoCode).where(
                BillingPromoCode.code_hash == hash_promo_code("WAI-DUPLICATE")
            )
        )
    ).scalar_one()
    promo.redeemed_count = 2
    await db_session.flush()
    listed = await client.get(
        "/api/admin/promo-codes?active=true&include_archived=true&limit=0",
        headers=admin_headers,
    )
    existing_get = await client.get(
        f"/api/admin/promo-codes/{created.json()['id']}", headers=admin_headers
    )
    missing_get = await client.get(f"/api/admin/promo-codes/{uuid4()}", headers=admin_headers)
    too_low = await client.patch(
        f"/api/admin/promo-codes/{created.json()['id']}",
        headers=admin_headers,
        json={"max_redemptions": 1},
    )
    archived = await client.delete(
        f"/api/admin/promo-codes/{created.json()['id']}", headers=admin_headers
    )
    archived_patch = await client.patch(
        f"/api/admin/promo-codes/{created.json()['id']}",
        headers=admin_headers,
        json={"active": True},
    )
    missing_archive = await client.delete(
        f"/api/admin/promo-codes/{uuid4()}", headers=admin_headers
    )

    assert missing_plan.status_code == 400
    assert invalid_prefix.status_code == 422
    assert invalid_code.status_code == 422
    assert auto_created.status_code == 200
    assert auto_created.json()["code"].startswith("SUPPORT-")
    assert auto_created.json()["note"] is None
    assert auto_created.json()["expires_at"] is None
    assert created.status_code == 200
    assert created.json()["note"] == "duplicate test"
    assert duplicate.status_code == 409
    assert listed.status_code == 200
    assert existing_get.status_code == 200
    assert existing_get.json()["id"] == created.json()["id"]
    assert missing_get.status_code == 404
    assert too_low.status_code == 400
    assert archived.status_code == 204
    assert archived_patch.status_code == 404
    assert missing_archive.status_code == 404


@pytest.mark.asyncio
async def test_admin_can_pause_and_reactivate_user_account(
    client: AsyncClient,
    db_session: AsyncSession,
):
    admin_payload, admin_headers = await _register(client, "admin-users@example.com")
    user_payload, user_headers = await _register(client, "pause-me@example.com")
    await _grant_admin(db_session, admin_payload["user_id"])

    paused = await client.patch(
        f"/api/admin/users/{user_payload['user_id']}/status",
        headers=admin_headers,
        json={"status": "paused", "reason": "support hold"},
    )
    assert paused.status_code == 200
    assert paused.json()["account_status"] == "paused"

    blocked = await client.get("/api/auth/me", headers=user_headers)
    assert blocked.status_code == 403
    assert blocked.json()["detail"] == "Account paused"

    active = await client.patch(
        f"/api/admin/users/{user_payload['user_id']}/status",
        headers=admin_headers,
        json={"status": "active", "reason": "resolved"},
    )
    assert active.status_code == 200

    allowed = await client.get("/api/auth/me", headers=user_headers)
    assert allowed.status_code == 200
    assert allowed.json()["email"] == "pause-me@example.com"


@pytest.mark.asyncio
async def test_admin_user_detail_billing_audit_and_deactivation_revocation(
    client: AsyncClient,
    db_session: AsyncSession,
):
    admin_payload, admin_headers = await _register(client, "admin-user-detail@example.com")
    user_payload, user_headers = await _register(client, "detail-user@example.com")
    await _grant_admin(db_session, admin_payload["user_id"])
    user_id = user_payload["user_id"]
    now = datetime.now(timezone.utc)
    plan = (await db_session.execute(select(Plan).where(Plan.code == "pro"))).scalar_one()
    sub = Subscription(
        user_id=user_id,
        plan_id=plan.id,
        status="active",
        provider="stripe",
        billing_period="month",
        current_period_end=now + timedelta(days=30),
        cancel_at_period_end=False,
    )
    db_session.add(sub)
    await db_session.flush()
    user = await db_session.get(User, user_id)
    assert user is not None
    user.current_subscription_id = sub.id
    promo = BillingPromoCode(
        code_hash=hash_promo_code("WAI-DETAIL"),
        plan_id=plan.id,
        billing_period="month",
        duration_days=30,
        max_redemptions=5,
        note="detail promo",
    )
    db_session.add(promo)
    await db_session.flush()
    db_session.add_all(
        [
            Recording(
                user_id=user_id,
                title="Detail recording",
                type="meeting",
                status="ready",
                duration_seconds=7200,
                billed_word_count=1500,
            ),
            DictationEntry(
                user_id=user_id,
                client_entry_id=uuid4(),
                raw_text="hello from dictation",
                duration_seconds=120.5,
                word_count=3,
                occurred_at=now,
            ),
            BillingPromoRedemption(
                promo_code_id=promo.id,
                user_id=user_id,
                subscription_id=sub.id,
            ),
            UsageWeek(
                user_id=user_id,
                week_start_utc=date(2026, 5, 24),
                words_used=123,
            ),
            Invoice(
                subscription_id=sub.id,
                amount=Decimal("12.00"),
                currency="USD",
                status="paid",
                provider_payment_id="pi_detail",
                paid_at=now,
            ),
            RefreshToken(
                user_id=user_id,
                token_hash="refresh-detail",
                expires_at=now + timedelta(days=30),
            ),
            ApiKey(
                user_id=user_id,
                name="detail key",
                token_hash="a" * 64,
                prefix="wc_live",
                last4="tail",
                scopes=["read"],
            ),
        ]
    )
    conversation = Conversation(user_id=user_id, title="Detail chat")
    db_session.add(conversation)
    await db_session.flush()
    db_session.add(
        ChatMessage(
            conversation_id=conversation.id,
            role="assistant",
            content=[],
            input_tokens=100,
            output_tokens=40,
            cached_tokens=25,
        )
    )
    await db_session.flush()

    users = await client.get(
        "/api/admin/users?q=detail-user&account_status=active&limit=1",
        headers=admin_headers,
    )
    detail = await client.get(f"/api/admin/users/{user_id}", headers=admin_headers)
    missing_detail = await client.get(f"/api/admin/users/{uuid4()}", headers=admin_headers)
    billing = await client.get("/api/admin/billing?limit=1", headers=admin_headers)
    self_pause = await client.patch(
        f"/api/admin/users/{admin_payload['user_id']}/status",
        headers=admin_headers,
        json={"status": "paused", "reason": "self hold"},
    )
    deactivated = await client.patch(
        f"/api/admin/users/{user_id}/status",
        headers=admin_headers,
        json={"status": "deactivated", "reason": "abuse review"},
    )
    missing_status = await client.patch(
        f"/api/admin/users/{uuid4()}/status",
        headers=admin_headers,
        json={"status": "paused", "reason": "missing"},
    )
    missing_grant = await client.post(
        f"/api/admin/users/{uuid4()}/subscriptions/grant",
        headers=admin_headers,
        json={"duration_days": 1, "reason": "missing"},
    )
    blocked = await client.get("/api/auth/me", headers=user_headers)
    audit = await client.get("/api/admin/audit?limit=1", headers=admin_headers)

    assert users.status_code == 200
    assert users.json()["items"][0]["email"] == "detail-user@example.com"
    assert detail.status_code == 200
    assert detail.json()["subscriptions"][0]["id"] == str(sub.id)
    assert detail.json()["promo_redemptions"][0]["promo_note"] == "detail promo"
    assert detail.json()["weekly_usage"][0]["words_used"] == 123
    assert detail.json()["recording_duration_seconds"] == 7200
    assert detail.json()["dictation_duration_seconds"] == 120.5
    assert detail.json()["transcription_duration_seconds"] == 7320.5
    assert detail.json()["companion_input_tokens"] == 100
    assert detail.json()["companion_output_tokens"] == 40
    assert detail.json()["companion_cached_tokens"] == 25
    assert detail.json()["companion_total_tokens"] == 140
    assert detail.json()["revenue_by_currency"] == {"USD": 12.0}
    assert missing_detail.status_code == 404
    assert billing.status_code == 200
    assert billing.json()["items"][0]["invoices"][0]["provider_payment_id"] == "pi_detail"
    assert self_pause.status_code == 400
    assert deactivated.status_code == 200
    assert missing_status.status_code == 404
    assert missing_grant.status_code == 404
    assert blocked.status_code == 403
    assert blocked.json()["detail"] == "Account deactivated"
    token = (
        await db_session.execute(
            select(RefreshToken).where(RefreshToken.token_hash == "refresh-detail")
        )
    ).scalar_one()
    key = (
        await db_session.execute(select(ApiKey).where(ApiKey.token_hash == "a" * 64))
    ).scalar_one()
    assert token.expires_at <= datetime.now(timezone.utc)
    assert key.revoked_at is not None
    assert audit.status_code == 200
    assert audit.json()["items"][0]["action"] == "user_status_update"
    assert audit.json()["items"][0]["actor_staff_member_id"] is not None


@pytest.mark.asyncio
async def test_admin_can_grant_pro_entitlement_to_user(
    client: AsyncClient,
    db_session: AsyncSession,
):
    admin_payload, admin_headers = await _register(client, "admin-grants@example.com")
    user_payload, user_headers = await _register(client, "grant-me@example.com")
    await _grant_admin(db_session, admin_payload["user_id"])

    grant = await client.post(
        f"/api/admin/users/{user_payload['user_id']}/subscriptions/grant",
        headers=admin_headers,
        json={"duration_days": 45, "reason": "manual customer support"},
    )
    assert grant.status_code == 200
    assert grant.json()["provider"] == "admin"
    assert grant.json()["status"] == "active"

    subscription = await client.get("/api/billing/subscription", headers=user_headers)
    assert subscription.status_code == 200
    assert subscription.json()["plan"]["code"] == "pro"
    assert subscription.json()["provider"] == "admin"


@pytest.mark.asyncio
async def test_admin_extends_existing_admin_entitlement(
    client: AsyncClient,
    db_session: AsyncSession,
):
    admin_payload, admin_headers = await _register(client, "admin-extend@example.com")
    user_payload, _ = await _register(client, "extend-me@example.com")
    await _grant_admin(db_session, admin_payload["user_id"])

    first = await client.post(
        f"/api/admin/users/{user_payload['user_id']}/subscriptions/grant",
        headers=admin_headers,
        json={"duration_days": 10, "reason": "first"},
    )
    second = await client.post(
        f"/api/admin/users/{user_payload['user_id']}/subscriptions/grant",
        headers=admin_headers,
        json={"duration_days": 10, "reason": "second"},
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["id"] == second.json()["id"]


@pytest.mark.asyncio
async def test_admin_stats_are_privacy_safe_and_aggregated(
    client: AsyncClient,
    db_session: AsyncSession,
):
    admin_payload, admin_headers = await _register(client, "admin-stats@example.com")
    user_payload, _ = await _register(client, "stats-user@example.com")
    await _grant_admin(db_session, admin_payload["user_id"])
    user_id = user_payload["user_id"]
    now = datetime(2026, 5, 25, 12, 0, tzinfo=timezone.utc)

    recording = Recording(
        user_id=user_id,
        title="Private filename should not leak",
        type="meeting",
        status="ready",
        duration_seconds=120,
        billed_word_count=7,
        created_at=now,
    )
    db_session.add(recording)
    await db_session.flush()
    db_session.add_all(
        [
            Segment(
                recording_id=recording.id,
                content="private transcript words",
                start_ms=0,
                end_ms=1000,
            ),
            DictationEntry(
                user_id=user_id,
                client_entry_id=uuid4(),
                raw_text="secret raw dictation",
                cleaned_text="secret cleaned dictation",
                duration_seconds=5,
                word_count=3,
                occurred_at=now,
            ),
        ]
    )
    plan = (await db_session.execute(select(Plan).where(Plan.code == "pro"))).scalar_one()
    sub = Subscription(
        user_id=user_id,
        plan_id=plan.id,
        status="active",
        provider="stripe",
        billing_period="month",
        created_at=now,
    )
    db_session.add(sub)
    await db_session.flush()
    db_session.add(
        Invoice(
            subscription_id=sub.id,
            amount=Decimal("12.00"),
            currency="USD",
            status="paid",
            provider_payment_id="pi_stats",
            paid_at=now,
        )
    )
    db_session.add_all(
        [
            BillingPromoCode(
                code_hash=hash_promo_code("WAI-REDEEMED-STATS"),
                plan_id=plan.id,
                billing_period="month",
                duration_days=30,
                max_redemptions=2,
                redeemed_count=1,
                created_at=now,
            ),
            BillingPromoCode(
                code_hash=hash_promo_code("WAI-ARCHIVED-STATS"),
                plan_id=plan.id,
                billing_period="month",
                duration_days=30,
                max_redemptions=1,
                archived_at=now,
            ),
            BillingPromoCode(
                code_hash=hash_promo_code("WAI-EXPIRED-STATS"),
                plan_id=plan.id,
                billing_period="month",
                duration_days=30,
                max_redemptions=1,
                expires_at=now - timedelta(days=1),
            ),
            BillingPromoCode(
                code_hash=hash_promo_code("WAI-EXHAUSTED-STATS"),
                plan_id=plan.id,
                billing_period="month",
                duration_days=30,
                max_redemptions=1,
                redeemed_count=1,
                active=False,
            ),
        ]
    )
    await db_session.flush()
    redeemed_promo = (
        await db_session.execute(
            select(BillingPromoCode).where(
                BillingPromoCode.code_hash == hash_promo_code("WAI-REDEEMED-STATS")
            )
        )
    ).scalar_one()
    db_session.add(
        BillingPromoRedemption(
            promo_code_id=redeemed_promo.id,
            user_id=user_id,
            subscription_id=sub.id,
            created_at=now,
        )
    )
    await db_session.flush()

    response = await client.get("/api/admin/stats", headers=admin_headers)

    assert response.status_code == 200
    payload = response.json()
    assert payload["users"]["total"] == 1
    assert payload["usage"]["recording_words"] == 7
    assert payload["usage"]["dictation_words"] == 3
    assert payload["usage"]["recording_duration_seconds"] == 120
    assert payload["billing"]["revenue_by_currency"]["USD"] == 12.0
    assert payload["promo"]["archived"] >= 1
    assert payload["promo"]["expired"] >= 1
    assert payload["promo"]["exhausted"] >= 1
    assert payload["promo"]["paused"] >= 1
    monthly_usage = {row["period"]: row for row in payload["usage"]["monthly"]}
    yearly_usage = {row["period"]: row for row in payload["usage"]["yearly"]}
    assert monthly_usage["2026-05"]["recording_words"] == 7
    assert monthly_usage["2026-05"]["dictation_words"] == 3
    assert monthly_usage["2026-05"]["total_words"] == 10
    assert yearly_usage["2026"]["recording_duration_seconds"] == 120
    monthly_revenue = payload["billing"]["monthly_revenue"]
    assert monthly_revenue == [{"period": "2026-05", "currency": "USD", "amount": 12.0}]
    monthly_redemptions = {
        row["period"]: row["redemptions"]
        for row in payload["promo"]["monthly_redemptions"]
    }
    assert monthly_redemptions["2026-05"] == 1
    assert "Private filename" not in str(payload)
    assert "secret raw dictation" not in str(payload)


@pytest.mark.asyncio
async def test_admin_observability_snapshot_flags_recording_pipeline_risks(
    client: AsyncClient,
    db_session: AsyncSession,
):
    admin_payload, admin_headers = await _register(client, "admin-observability@example.com")
    user_payload, _ = await _register(client, "observability-user@example.com")
    await _grant_admin(db_session, admin_payload["user_id"])
    user_id = user_payload["user_id"]
    now = datetime.now(timezone.utc)

    healthy = Recording(
        user_id=user_id,
        title="Private healthy recording title",
        type="meeting",
        status="ready",
        duration_seconds=120,
        billed_word_count=20,
        created_at=now - timedelta(minutes=10),
        updated_at=now - timedelta(minutes=9),
    )
    low_coverage = Recording(
        user_id=user_id,
        title="Private low coverage title",
        type="meeting",
        status="ready",
        duration_seconds=1800,
        billed_word_count=25,
        created_at=now - timedelta(minutes=20),
        updated_at=now - timedelta(minutes=18),
    )
    stuck = Recording(
        user_id=user_id,
        title="Private stuck recording title",
        type="meeting",
        status="processing",
        duration_seconds=900,
        # Stuck = processing longer than recording_processing_stale_after_minutes
        # (480 since f97b5bc6 raised it from 15). Still inside the 24h window.
        created_at=now - timedelta(hours=11),
        updated_at=now - timedelta(hours=10),
    )
    failed = Recording(
        user_id=user_id,
        title="Private failed recording title",
        type="meeting",
        status="failed",
        failure_code="stt_provider_error",
        failure_message="Raw provider message must not leak",
        created_at=now - timedelta(minutes=30),
        updated_at=now - timedelta(minutes=29),
    )
    db_session.add_all([healthy, low_coverage, stuck, failed])
    await db_session.flush()
    db_session.add_all(
        [
            Segment(
                recording_id=healthy.id,
                speaker="speaker_0",
                content="private healthy transcript",
                start_ms=0,
                end_ms=120_000,
            ),
            Segment(
                recording_id=low_coverage.id,
                speaker="speaker_0",
                content="private partial transcript",
                start_ms=0,
                end_ms=120_000,
            ),
        ]
    )
    await db_session.flush()

    response = await client.get("/api/admin/observability", headers=admin_headers)

    assert response.status_code == 200
    payload = response.json()
    assert payload["recording_pipeline"]["status_counts"]["ready"] >= 2
    assert payload["recording_pipeline"]["stuck_processing_count"] >= 1
    assert payload["recording_pipeline"]["low_transcript_coverage_count_24h"] >= 1
    assert payload["recording_pipeline"]["segments_missing_embedding_count"] >= 1
    assert payload["recording_pipeline"]["recordings_with_degraded_embeddings_24h"] >= 1
    assert payload["recording_pipeline"]["failed_rate_24h"] > 0
    alert_codes = {item["code"] for item in payload["alerts"]}
    assert "recording.processing.stuck" in alert_codes
    assert "recording.transcript.low_coverage" in alert_codes
    assert "recording.embeddings.degraded" in alert_codes
    assert payload["sentry"]["configured"] in {True, False}
    assert payload["server"]["database"] == "connected"
    assert "Private" not in str(payload)
    assert "Raw provider" not in str(payload)
    assert "private partial transcript" not in str(payload)


@pytest.mark.asyncio
async def test_admin_can_trigger_embedding_backfill(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    admin_payload, admin_headers = await _register(
        client,
        "admin-embedding-backfill@example.com",
    )
    await _grant_admin(db_session, admin_payload["user_id"])

    async def fake_backfill(db, *, user_id=None, batch_size=64, limit=512):
        del db, user_id, batch_size, limit

        class Result:
            def as_dict(self) -> dict:
                return {
                    "scanned": 2,
                    "filled": 2,
                    "failed": 0,
                    "remaining": 0,
                    "batches": 1,
                    "isolated_failures": 0,
                }

        return Result()

    monkeypatch.setattr(
        "app.api.routes.admin.backfill_missing_segment_embeddings",
        fake_backfill,
    )

    response = await client.post(
        "/api/admin/embeddings/backfill",
        headers=admin_headers,
        json={"limit": 10, "batch_size": 2},
    )

    assert response.status_code == 200
    assert response.json()["filled"] == 2
    assert response.json()["remaining"] == 0


@pytest.mark.asyncio
async def test_admin_subscription_provider_actions_are_audited(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    admin_payload, admin_headers = await _register(client, "admin-provider@example.com")
    user_payload, _ = await _register(client, "provider-user@example.com")
    await _grant_admin(db_session, admin_payload["user_id"])
    plan = (await db_session.execute(select(Plan).where(Plan.code == "pro"))).scalar_one()
    sub = Subscription(
        user_id=user_payload["user_id"],
        plan_id=plan.id,
        status="active",
        provider="stripe",
        billing_period="month",
        stripe_subscription_id="sub_admin_test",
    )
    db_session.add(sub)
    await db_session.flush()
    invoice = Invoice(
        subscription_id=sub.id,
        amount=Decimal("12.00"),
        currency="USD",
        status="paid",
        provider_payment_id="pi_admin_refund",
        paid_at=datetime.now(timezone.utc),
    )
    db_session.add(invoice)
    tinkoff_sub = Subscription(
        user_id=user_payload["user_id"],
        plan_id=plan.id,
        status="active",
        provider="tinkoff",
        billing_period="month",
    )
    unsupported_sub = Subscription(
        user_id=user_payload["user_id"],
        plan_id=plan.id,
        status="active",
        provider="admin",
        billing_period="month",
    )
    db_session.add_all([tinkoff_sub, unsupported_sub])
    await db_session.flush()
    stripe_missing_id_sub = Subscription(
        user_id=user_payload["user_id"],
        plan_id=plan.id,
        status="active",
        provider="stripe",
        billing_period="month",
    )
    db_session.add(stripe_missing_id_sub)
    await db_session.flush()
    tinkoff_invoice = Invoice(
        subscription_id=tinkoff_sub.id,
        amount=Decimal("12.00"),
        currency="RUB",
        status="paid",
        provider_payment_id="tb_payment",
        paid_at=datetime.now(timezone.utc),
    )
    unsupported_invoice = Invoice(
        subscription_id=unsupported_sub.id,
        amount=Decimal("12.00"),
        currency="USD",
        status="paid",
        provider_payment_id="admin_payment",
        paid_at=datetime.now(timezone.utc),
    )
    missing_provider_payment_invoice = Invoice(
        subscription_id=tinkoff_sub.id,
        amount=Decimal("12.00"),
        currency="RUB",
        status="paid",
        paid_at=datetime.now(timezone.utc),
    )
    db_session.add_all([tinkoff_invoice, unsupported_invoice, missing_provider_payment_invoice])
    await db_session.flush()

    calls: list[tuple[str, str, object]] = []

    async def fake_cancel(self, provider_subscription_id: str, *, at_period_end: bool = True):
        calls.append(("cancel", provider_subscription_id, at_period_end))

    async def fake_resume(self, provider_subscription_id: str):
        calls.append(("resume", provider_subscription_id, None))

    async def fake_refund(
        self,
        payment_id: str,
        *,
        amount_minor: int | None = None,
        reason: str | None = None,
    ):
        calls.append(("refund", payment_id, amount_minor))
        return {"id": "re_admin_test", "status": "succeeded"}

    async def fake_tinkoff_cancel(self, payment_id: str, *, amount_kopecks: int | None = None):
        calls.append(("tinkoff_refund", payment_id, amount_kopecks))
        return {"Success": True, "Status": "PARTIAL_REFUNDED"}

    monkeypatch.setattr(
        "app.billing.providers.stripe_provider.StripeProvider.cancel_subscription",
        fake_cancel,
    )
    monkeypatch.setattr(
        "app.billing.providers.stripe_provider.StripeProvider.resume_subscription",
        fake_resume,
    )
    monkeypatch.setattr(
        "app.billing.providers.stripe_provider.StripeProvider.refund_payment",
        fake_refund,
    )
    monkeypatch.setattr(
        "app.billing.providers.tinkoff_provider.TinkoffProvider.cancel_payment",
        fake_tinkoff_cancel,
    )

    cancel = await client.post(
        f"/api/admin/subscriptions/{sub.id}/cancel",
        headers=admin_headers,
        json={"mode": "period_end", "reason": "admin test"},
    )
    resume = await client.post(
        f"/api/admin/subscriptions/{sub.id}/resume",
        headers=admin_headers,
        json={"reason": "admin test resume"},
    )
    immediate_cancel = await client.post(
        f"/api/admin/subscriptions/{sub.id}/cancel",
        headers=admin_headers,
        json={"mode": "immediate", "reason": "admin immediate"},
    )
    canceled_resume = await client.post(
        f"/api/admin/subscriptions/{sub.id}/resume",
        headers=admin_headers,
        json={"reason": "reactivate canceled subscription"},
    )
    refund = await client.post(
        f"/api/admin/invoices/{invoice.id}/refund",
        headers=admin_headers,
        json={"reason": "requested_by_customer"},
    )
    tinkoff_refund = await client.post(
        f"/api/admin/invoices/{tinkoff_invoice.id}/refund",
        headers=admin_headers,
        json={"amount_minor": 500, "reason": "partial"},
    )
    unsupported_refund = await client.post(
        f"/api/admin/invoices/{unsupported_invoice.id}/refund",
        headers=admin_headers,
        json={"reason": "unsupported"},
    )
    missing_cancel = await client.post(
        f"/api/admin/subscriptions/{uuid4()}/cancel",
        headers=admin_headers,
        json={"mode": "period_end", "reason": "missing"},
    )
    stripe_missing_id_cancel = await client.post(
        f"/api/admin/subscriptions/{stripe_missing_id_sub.id}/cancel",
        headers=admin_headers,
        json={"mode": "period_end", "reason": "missing stripe id"},
    )
    missing_resume = await client.post(
        f"/api/admin/subscriptions/{uuid4()}/resume",
        headers=admin_headers,
        json={"reason": "missing"},
    )
    stripe_missing_id_resume = await client.post(
        f"/api/admin/subscriptions/{stripe_missing_id_sub.id}/resume",
        headers=admin_headers,
        json={"reason": "missing stripe id"},
    )
    missing_invoice = await client.post(
        f"/api/admin/invoices/{uuid4()}/refund",
        headers=admin_headers,
        json={"reason": "missing"},
    )
    missing_provider_payment = await client.post(
        f"/api/admin/invoices/{missing_provider_payment_invoice.id}/refund",
        headers=admin_headers,
        json={"reason": "missing provider payment"},
    )

    assert cancel.status_code == 200
    assert resume.status_code == 200
    assert immediate_cancel.status_code == 200
    assert canceled_resume.status_code == 200
    assert refund.status_code == 200
    assert tinkoff_refund.status_code == 200
    assert unsupported_refund.status_code == 400
    assert missing_cancel.status_code == 404
    assert stripe_missing_id_cancel.status_code == 400
    assert missing_resume.status_code == 404
    assert stripe_missing_id_resume.status_code == 400
    assert missing_invoice.status_code == 404
    assert missing_provider_payment.status_code == 400
    assert calls == [
        ("cancel", "sub_admin_test", True),
        ("resume", "sub_admin_test", None),
        ("cancel", "sub_admin_test", False),
        ("resume", "sub_admin_test", None),
        ("refund", "pi_admin_refund", None),
        ("tinkoff_refund", "tb_payment", 500),
    ]
    await db_session.refresh(invoice)
    await db_session.refresh(tinkoff_invoice)
    assert invoice.status == "refunded"
    assert tinkoff_invoice.status == "partially_refunded"
    events = (
        await db_session.execute(
            select(BillingEvent).where(BillingEvent.type.like("admin.%"))
        )
    ).scalars().all()
    assert {event.type for event in events} >= {
        "admin.subscription_cancel",
        "admin.subscription_resume",
        "admin.invoice_refund",
    }


@pytest.mark.asyncio
async def test_admin_deepgram_usage_shows_detailed_burn_analysis(
    client: AsyncClient,
    db_session: AsyncSession,
):
    admin_payload, admin_headers = await _register(client, "admin-deepgram@example.com")
    user_payload, _ = await _register(client, "deepgram-user@example.com")
    await _grant_admin(db_session, admin_payload["user_id"])
    user_id = user_payload["user_id"]
    now = datetime.now(timezone.utc)

    recording = Recording(
        user_id=user_id,
        title="Private recording title",
        type="meeting",
        status="failed",
        failure_code="provider_unavailable",
        uploaded_at=now,
        duration_seconds=120,
        billed_word_count=0,
        created_at=now,
    )
    db_session.add(recording)
    await db_session.flush()
    db_session.add_all(
        [
            DictationEntry(
                user_id=user_id,
                client_entry_id=uuid4(),
                raw_text="private dictation text",
                duration_seconds=5,
                word_count=2,
                occurred_at=now,
            ),
            DeepgramUsageEvent(
                user_id=user_id,
                recording_id=recording.id,
                operation="file_stt",
                purpose="recording",
                status="failed",
                model="nova-3",
                language="ru",
                content_type="audio/mp4",
                audio_seconds=120,
                billable_seconds=0,
                audio_bytes=36066,
                provider_status_code=402,
                provider_error_code="ASR_PAYMENT_REQUIRED",
                created_at=now,
            ),
            DeepgramUsageEvent(
                user_id=user_id,
                recording_id=recording.id,
                operation="file_stt",
                purpose="recording",
                status="refused",
                model="nova-3",
                language="ru",
                content_type="audio/mp4",
                audio_seconds=120,
                billable_seconds=0,
                audio_bytes=36066,
                guard_code="provider_unavailable",
                created_at=now,
            ),
        ]
    )
    await db_session.flush()

    response = await client.get("/api/admin/deepgram-usage?days=7", headers=admin_headers)

    assert response.status_code == 200
    payload = response.json()
    assert payload["captured"]["events"] == 2
    assert payload["captured"]["failed"] == 1
    assert payload["captured"]["refused"] == 1
    assert payload["captured"]["provider_402"] == 1
    assert payload["estimated"]["recording_seconds"] == 120
    assert payload["estimated"]["dictation_seconds"] == 5
    assert payload["by_user"][0]["email"] == "deepgram-user@example.com"
    assert payload["top_recordings"][0]["captured_events"] == 2
    assert {
        "deepgram.provider.payment_required",
        "deepgram.recording.repeated_attempts",
    }.issubset({item["code"] for item in payload["analysis"]})
    assert "Private recording title" not in str(payload)
    assert "private dictation text" not in str(payload)


@pytest.mark.asyncio
async def test_admin_ai_usage_shows_model_provider_user_and_error_breakdowns(
    client: AsyncClient,
    db_session: AsyncSession,
):
    admin_payload, admin_headers = await _register(client, "admin-ai-usage@example.com")
    user_a_payload, _ = await _register(client, "ai-usage-a@example.com")
    user_b_payload, _ = await _register(client, "ai-usage-b@example.com")
    await _grant_admin(db_session, admin_payload["user_id"])
    now = datetime.now(timezone.utc)

    db_session.add_all(
        [
            AiUsageEvent(
                user_id=user_a_payload["user_id"],
                provider="openai",
                feature="companion",
                operation="companion.turn",
                status="succeeded",
                model="gpt-5.5",
                input_tokens=3_000,
                output_tokens=2_000,
                cached_tokens=500,
                total_tokens=5_000,
                estimated_cost_usd=0.12,
                pricing_status="priced",
                latency_ms=100,
                created_at=now,
            ),
            AiUsageEvent(
                user_id=user_a_payload["user_id"],
                provider="deepgram",
                feature="dictation",
                operation="realtime.session_mint",
                status="refused",
                model="nova-3",
                billable_seconds=0,
                pricing_status="unpriced",
                guard_code="realtime.session_mint.breaker_open",
                latency_ms=5,
                created_at=now,
            ),
            AiUsageEvent(
                user_id=user_b_payload["user_id"],
                provider="openai",
                feature="materials",
                operation="summary.content",
                status="failed",
                model="gpt-5.5",
                input_tokens=100,
                total_tokens=100,
                estimated_cost_usd=0,
                pricing_status="unpriced",
                error_type="APIStatusError",
                created_at=now,
                details={"source": "test", "prompt": "private prompt must not leak"},
            ),
        ]
    )
    await db_session.flush()

    response = await client.get("/api/admin/ai-usage?days=7", headers=admin_headers)

    assert response.status_code == 200
    payload = response.json()
    assert payload["summary"]["events"] == 3
    assert payload["summary"]["estimated_cost_usd"] == 0.12
    assert payload["summary"]["total_tokens"] == 5_100
    assert payload["summary"]["failed_events"] == 1
    assert payload["summary"]["refused_events"] == 1
    assert payload["summary"]["unpriced_events"] == 2
    assert payload["by_provider"][0]["provider"] == "openai"
    assert payload["by_provider"][0]["events"] == 2
    assert {row["feature"] for row in payload["by_feature"]} == {
        "companion",
        "dictation",
        "materials",
    }
    assert payload["by_user"][0]["email"] == "ai-usage-a@example.com"
    assert payload["by_user"][0]["events"] == 2
    assert payload["by_model"][0]["model"] == "gpt-5.5"
    assert {
        "ai_usage.unpriced_models",
        "ai_usage.provider.deepgram.errors",
    }.issubset({item["code"] for item in payload["analysis"]})
    assert "private prompt" not in str(payload)

    filtered = await client.get(
        "/api/admin/ai-usage?days=7&q=ai-usage-a&provider=deepgram",
        headers=admin_headers,
    )
    assert filtered.status_code == 200
    filtered_payload = filtered.json()
    assert filtered_payload["summary"]["events"] == 1
    assert filtered_payload["by_user"][0]["email"] == "ai-usage-a@example.com"
    assert filtered_payload["by_provider"][0]["provider"] == "deepgram"
