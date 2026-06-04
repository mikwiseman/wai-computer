"""Tests for WaiBrain Spaces: shareable canonical mini-brains."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from app.core import brain_spaces as brain_space_service
from app.core.item_ingest import ingest_item
from app.models.brain_space import BrainClaim, BrainPage, BrainReviewPack, BrainSpace
from app.models.recording import Recording
from app.models.user import User

pytestmark = pytest.mark.asyncio


LEGAL_ACCEPTANCE = {
    "accepted_legal_terms": True,
    "legal_terms_version": "2026-05-22",
    "legal_privacy_version": "2026-05-22",
}


async def _register(client, email: str | None = None) -> tuple[dict, str]:
    email = email or f"brain-{uuid4().hex}@example.com"
    response = await client.post(
        "/api/auth/register",
        json={"email": email, "password": "testpassword123", **LEGAL_ACCEPTANCE},
    )
    assert response.status_code == 200, response.text
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}, email


async def _db_user(db_session, email: str | None = None) -> User:
    user = User(email=email or f"brain-db-{uuid4().hex}@example.com", password_hash="x")
    db_session.add(user)
    await db_session.flush()
    return user


async def test_spaces_default_create_page_source_home_and_export(
    client,
    auth_headers,
    db_session,
) -> None:
    spaces_response = await client.get("/api/brain/spaces", headers=auth_headers)
    assert spaces_response.status_code == 200, spaces_response.text
    spaces = spaces_response.json()["spaces"]
    assert len(spaces) == 1
    assert spaces[0]["name"] == "Personal"
    assert spaces[0]["role"] == "owner"

    created = await client.post(
        "/api/brain/spaces",
        headers=auth_headers,
        json={
            "name": "Wai School",
            "kind": "work",
            "engine_profile": "waibrain",
            "description": "Shared operating brain for Wai School.",
        },
    )
    assert created.status_code == 201, created.text
    space = created.json()
    assert space["slug"] == "wai-school"
    assert space["engine_profile"] == "waibrain"

    item, _ = await ingest_item(
        db_session,
        space["owner_user_id"],
        source="paste",
        title="Parent call notes",
        body="For younger students, use 40 minute sessions.",
        embed=False,
    )
    await db_session.commit()

    link = await client.post(
        f"/api/brain/spaces/{space['id']}/sources",
        headers=auth_headers,
        json={"source_kind": "item", "source_id": str(item.id)},
    )
    assert link.status_code == 201, link.text
    assert link.json()["source_title"] == "Parent call notes"

    page_response = await client.post(
        f"/api/brain/spaces/{space['id']}/pages",
        headers=auth_headers,
        json={
            "title": "Customer stage rules",
            "kind": "workflow",
            "claims": [
                {
                    "kind": "workflow_rule",
                    "text": "For younger students, prefer 40 minute intro sessions.",
                    "confidence": 0.91,
                    "authority": "self",
                    "evidence": [
                        {
                            "source_kind": "item",
                            "source_id": str(item.id),
                            "title": "Parent call notes",
                        }
                    ],
                }
            ],
        },
    )
    assert page_response.status_code == 201, page_response.text
    page = page_response.json()
    assert page["slug"] == "customer-stage-rules"
    assert "wai_type: brain_page" in page["markdown"]
    assert page["claims"][0]["kind"] == "workflow_rule"

    home = await client.get(f"/api/brain/spaces/{space['id']}/home", headers=auth_headers)
    assert home.status_code == 200, home.text
    data = home.json()
    assert data["space"]["name"] == "Wai School"
    assert data["page_count"] == 1
    assert data["source_count"] == 1
    assert data["claim_counts"]["workflow_rule"] == 1

    export = await client.get(
        f"/api/brain/spaces/{space['id']}/export?profile=obsidian",
        headers=auth_headers,
    )
    assert export.status_code == 200, export.text
    exported = export.json()
    assert exported["profile"] == "obsidian"
    assert exported["files"][0]["path"] == "Customer stage rules.md"

    persisted_pages = (
        await db_session.execute(select(BrainPage).where(BrainPage.space_id == space["id"]))
    ).scalars().all()
    persisted_claims = (
        await db_session.execute(select(BrainClaim).where(BrainClaim.space_id == space["id"]))
    ).scalars().all()
    assert len(persisted_pages) == 1
    assert len(persisted_claims) == 1


async def test_space_members_review_pack_match_and_context(client, auth_headers) -> None:
    member_headers, member_email = await _register(client)

    source_space = (
        await client.post(
            "/api/brain/spaces",
            headers=auth_headers,
            json={"name": "Mik Personal", "kind": "personal"},
        )
    ).json()
    target_space = (
        await client.post(
            "/api/brain/spaces",
            headers=auth_headers,
            json={"name": "Wai School Shared", "kind": "work"},
        )
    ).json()

    member = await client.post(
        f"/api/brain/spaces/{target_space['id']}/members",
        headers=auth_headers,
        json={"email": member_email, "role": "editor"},
    )
    assert member.status_code == 201, member.text

    visible = await client.get("/api/brain/spaces", headers=member_headers)
    assert visible.status_code == 200, visible.text
    assert {space["name"] for space in visible.json()["spaces"]} >= {
        "Personal",
        "Wai School Shared",
    }

    page = await client.post(
        f"/api/brain/spaces/{source_space['id']}/pages",
        headers=auth_headers,
        json={
            "title": "Customer stage rules",
            "kind": "workflow",
            "claims": [
                {
                    "kind": "fact",
                    "text": "Wai School sells through parent discovery calls.",
                    "confidence": 0.93,
                    "authority": "self",
                }
            ],
        },
    )
    assert page.status_code == 201, page.text

    match = await client.post(
        f"/api/brain/spaces/{target_space['id']}/match",
        headers=auth_headers,
        json={"other_space_id": source_space["id"]},
    )
    assert match.status_code == 201, match.text
    pack = match.json()
    assert pack["status"] == "pending"
    assert "Customer stage rules" in pack["summary"]

    member_accept = await client.post(
        f"/api/brain/spaces/{target_space['id']}/review-packs/{pack['id']}/accept",
        headers=member_headers,
    )
    assert member_accept.status_code == 403, member_accept.text

    owner_accept = await client.post(
        f"/api/brain/spaces/{target_space['id']}/review-packs/{pack['id']}/accept",
        headers=auth_headers,
    )
    assert owner_accept.status_code == 200, owner_accept.text
    assert owner_accept.json()["status"] == "accepted"

    context = await client.post(
        f"/api/brain/spaces/{target_space['id']}/context",
        headers=auth_headers,
        json={"task": "Write a parent call script."},
    )
    assert context.status_code == 200, context.text
    assert "Wai School sells through parent discovery calls." in context.json()["markdown"]

    listed_packs = await client.get(
        f"/api/brain/spaces/{target_space['id']}/review-packs",
        headers=auth_headers,
    )
    assert listed_packs.status_code == 200, listed_packs.text
    assert listed_packs.json()["review_packs"][0]["status"] == "accepted"

    assert (
        await client.get(
            f"/api/brain/spaces/{source_space['id']}/home", headers=member_headers
        )
    ).status_code == 404
    assert (
        await client.get(
            f"/api/brain/spaces/{target_space['id']}/home", headers=member_headers
        )
    ).status_code == 200

    # The match should have created canonical accepted knowledge inside the shared Space,
    # without granting the member access to the owner's private Space.
    persisted_pack_count = len(listed_packs.json()["review_packs"])
    assert persisted_pack_count == 1
    assert pack["id"]
    assert BrainSpace.__tablename__ == "brain_spaces"
    assert BrainReviewPack.__tablename__ == "brain_review_packs"


async def test_brain_space_service_validation_and_review_edges(db_session) -> None:
    owner = await _db_user(db_session)
    member = await _db_user(db_session, "brain-member@example.com")

    with pytest.raises(brain_space_service.BrainSpaceValidationError):
        await brain_space_service.create_space(db_session, owner.id, name="")
    with pytest.raises(brain_space_service.BrainSpaceValidationError):
        await brain_space_service.create_space(
            db_session,
            owner.id,
            name="Bad engine",
            engine_profile="bad",
        )

    default = await brain_space_service.ensure_default_space(db_session, owner.id)
    assert (await brain_space_service.ensure_default_space(db_session, owner.id)).id == default.id
    first = await brain_space_service.create_space(db_session, owner.id, name="Ops")
    second = await brain_space_service.create_space(db_session, owner.id, name="Ops")
    assert second.slug == "ops-2"

    with pytest.raises(brain_space_service.BrainSpaceValidationError):
        await brain_space_service.add_member(
            db_session,
            actor_user_id=owner.id,
            space_id=first.id,
            email=member.email,
            role="owner",
        )
    with pytest.raises(brain_space_service.BrainSpaceNotFoundError):
        await brain_space_service.add_member(
            db_session,
            actor_user_id=owner.id,
            space_id=first.id,
            email="missing@example.com",
            role="viewer",
        )
    added = await brain_space_service.add_member(
        db_session,
        actor_user_id=owner.id,
        space_id=first.id,
        email=member.email,
        role="viewer",
    )
    updated = await brain_space_service.add_member(
        db_session,
        actor_user_id=owner.id,
        space_id=first.id,
        email=member.email,
        role="editor",
    )
    assert added.id == updated.id
    assert updated.role == "editor"

    with pytest.raises(brain_space_service.BrainSpaceValidationError):
        await brain_space_service.create_page(
            db_session,
            actor_user_id=owner.id,
            space_id=first.id,
            title=" ",
        )
    invalid_claims = [
        {"kind": "bad", "text": "x"},
        {"kind": "fact", "text": ""},
        {"kind": "fact", "text": "x", "confidence": 2},
        {"kind": "fact", "text": "x", "evidence": "bad"},
    ]
    for claim in invalid_claims:
        with pytest.raises(brain_space_service.BrainSpaceValidationError):
            await brain_space_service.create_page(
                db_session,
                actor_user_id=owner.id,
                space_id=first.id,
                title=f"Invalid {uuid4()}",
                claims=[claim],
            )

    page = await brain_space_service.create_page(
        db_session,
        actor_user_id=owner.id,
        space_id=first.id,
        title="Operating rule",
        claims=[{"kind": "fact", "text": "Always document approvals.", "confidence": 0.91}],
    )
    duplicate_claim_page = await brain_space_service.create_page(
        db_session,
        actor_user_id=owner.id,
        space_id=first.id,
        title="Duplicate fact",
        claims=[{"kind": "fact", "text": "Always document approvals.", "confidence": 0.91}],
    )
    assert duplicate_claim_page.id != page.id
    assert len(
        (
            await db_session.execute(
                select(BrainClaim).where(BrainClaim.space_id == first.id)
            )
        ).scalars().all()
    ) == 1
    assert (await brain_space_service.get_page(db_session, user_id=owner.id, page_id=page.id)).id
    with pytest.raises(brain_space_service.BrainSpaceNotFoundError):
        await brain_space_service.get_page(db_session, user_id=owner.id, page_id=uuid4())

    assert brain_space_service._render_page_markdown(
        title="Manual",
        frontmatter={"wai_type": "brain_page"},
        body="---\ncustom: true\n---\n# Manual",
    ).startswith("---")

    auto_claim = await brain_space_service.propose_claim_review_pack(
        db_session,
        actor_user_id=owner.id,
        space_id=first.id,
        claim={"kind": "fact", "text": "High confidence fact.", "confidence": 0.95},
        page_title="Auto facts",
    )
    assert isinstance(auto_claim, BrainClaim)
    pack = await brain_space_service.propose_claim_review_pack(
        db_session,
        actor_user_id=owner.id,
        space_id=first.id,
        claim={
            "kind": "decision",
            "text": "Needs owner review.",
            "confidence": 0.55,
            "authority": "model",
        },
        page_title="Decisions",
    )
    assert isinstance(pack, BrainReviewPack)
    rejected = await brain_space_service.reject_review_pack(
        db_session,
        actor_user_id=owner.id,
        space_id=first.id,
        pack_id=pack.id,
        reason="not now",
    )
    assert rejected.status == "rejected"
    with pytest.raises(brain_space_service.BrainSpaceValidationError):
        await brain_space_service.reject_review_pack(
            db_session,
            actor_user_id=owner.id,
            space_id=first.id,
            pack_id=pack.id,
        )

    manual_pack = BrainReviewPack(
        space_id=first.id,
        kind="bridge",
        risk="medium",
        status="pending",
        title="Manual pack",
        summary="Manual",
        proposals=[
            {"type": "page_match", "title": "ignored"},
            {
                "type": "claim",
                "kind": "fact",
                "text": "Accepted from manual pack.",
                "confidence": 0.9,
                "authority": "connected",
                "page_title": "Manual accepted",
            },
        ],
        evidence=[],
        created_by_user_id=owner.id,
    )
    db_session.add(manual_pack)
    await db_session.flush()
    accepted = await brain_space_service.accept_review_pack(
        db_session,
        actor_user_id=owner.id,
        space_id=first.id,
        pack_id=manual_pack.id,
    )
    assert accepted.status == "accepted"
    with pytest.raises(brain_space_service.BrainSpaceValidationError):
        await brain_space_service.accept_review_pack(
            db_session,
            actor_user_id=owner.id,
            space_id=first.id,
            pack_id=manual_pack.id,
        )
    with pytest.raises(brain_space_service.BrainSpaceNotFoundError):
        await brain_space_service.accept_review_pack(
            db_session,
            actor_user_id=owner.id,
            space_id=first.id,
            pack_id=uuid4(),
        )

    context = await brain_space_service.build_context(
        db_session,
        user_id=owner.id,
        space_id=first.id,
    )
    assert "# Ops context" in context["markdown"]
    with pytest.raises(brain_space_service.BrainSpaceValidationError):
        await brain_space_service.export_space(
            db_session,
            user_id=owner.id,
            space_id=first.id,
            profile="bad",
        )
    gbrain = await brain_space_service.export_space(
        db_session,
        user_id=owner.id,
        space_id=first.id,
        profile="gbrain",
    )
    mempalace = await brain_space_service.export_space(
        db_session,
        user_id=owner.id,
        space_id=first.id,
        profile="mempalace",
    )
    assert gbrain["files"][0]["path"].startswith("compiled_truth/")
    assert mempalace["files"][0]["path"].startswith("Ops/")


async def test_brain_space_routes_secondary_paths_and_errors(
    client,
    auth_headers,
    db_session,
) -> None:
    member_headers, member_email = await _register(client, "brain-route-member@example.com")
    created = await client.post(
        "/api/brain/spaces",
        headers=auth_headers,
        json={"name": "Route Space", "kind": "work"},
    )
    assert created.status_code == 201, created.text
    space = created.json()

    bad_member = await client.post(
        f"/api/brain/spaces/{space['id']}/members",
        headers=auth_headers,
        json={"email": member_email, "role": "owner"},
    )
    assert bad_member.status_code == 422
    missing_member = await client.post(
        f"/api/brain/spaces/{space['id']}/members",
        headers=auth_headers,
        json={"email": "missing@example.com", "role": "viewer"},
    )
    assert missing_member.status_code == 404
    added_member = await client.post(
        f"/api/brain/spaces/{space['id']}/members",
        headers=auth_headers,
        json={"email": member_email, "role": "editor"},
    )
    assert added_member.status_code == 201, added_member.text

    page = await client.post(
        f"/api/brain/spaces/{space['id']}/pages",
        headers=member_headers,
        json={"title": "Route page", "markdown": "# Route page"},
    )
    assert page.status_code == 201, page.text
    pages = await client.get(f"/api/brain/spaces/{space['id']}/pages", headers=member_headers)
    assert pages.status_code == 200, pages.text
    assert pages.json()["pages"][0]["title"] == "Route page"

    invalid_source = await client.post(
        f"/api/brain/spaces/{space['id']}/sources",
        headers=auth_headers,
        json={"source_kind": "bad", "source_id": str(uuid4())},
    )
    assert invalid_source.status_code == 422
    missing_source = await client.post(
        f"/api/brain/spaces/{space['id']}/sources",
        headers=auth_headers,
        json={"source_kind": "item", "source_id": str(uuid4())},
    )
    assert missing_source.status_code == 404

    recording = Recording(
        user_id=UUID(space["owner_user_id"]),
        title="Route recording",
        type="meeting",
    )
    db_session.add(recording)
    await db_session.commit()
    recording_source = await client.post(
        f"/api/brain/spaces/{space['id']}/sources",
        headers=auth_headers,
        json={"source_kind": "recording", "source_id": str(recording.id)},
    )
    assert recording_source.status_code == 201, recording_source.text
    duplicate_source = await client.post(
        f"/api/brain/spaces/{space['id']}/sources",
        headers=auth_headers,
        json={"source_kind": "recording", "source_id": str(recording.id)},
    )
    assert duplicate_source.status_code == 201, duplicate_source.text
    assert duplicate_source.json()["id"] == recording_source.json()["id"]

    other = (
        await client.post(
            "/api/brain/spaces",
            headers=auth_headers,
            json={"name": "Empty source", "kind": "work"},
        )
    ).json()
    match = await client.post(
        f"/api/brain/spaces/{space['id']}/match",
        headers=auth_headers,
        json={"other_space_id": other["id"]},
    )
    assert match.status_code == 201, match.text
    assert "No reusable knowledge" in match.json()["summary"]
    filtered = await client.get(
        f"/api/brain/spaces/{space['id']}/review-packs?status=pending",
        headers=auth_headers,
    )
    assert filtered.status_code == 200, filtered.text
    assert filtered.json()["pending_count"] == 1
    rejected = await client.post(
        f"/api/brain/spaces/{space['id']}/review-packs/{match.json()['id']}/reject",
        headers=auth_headers,
        json={"reason": "not useful"},
    )
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["status"] == "rejected"

    invalid_export = await client.get(
        f"/api/brain/spaces/{space['id']}/export?profile=bad",
        headers=auth_headers,
    )
    assert invalid_export.status_code == 422
    hidden_home = await client.get(f"/api/brain/spaces/{other['id']}/home", headers=member_headers)
    assert hidden_home.status_code == 404
