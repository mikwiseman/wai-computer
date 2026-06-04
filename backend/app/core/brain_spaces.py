"""Service layer for WaiBrain Spaces.

This is intentionally deterministic and low-token: Space opens, exports, and
matches do not call an LLM. LLM extraction can produce review packs later, but
the canonical write path stays here so Markdown pages and claim indexes cannot
drift apart.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal

from sqlalchemy import and_, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.brain_space import (
    BrainClaim,
    BrainPage,
    BrainReviewPack,
    BrainSpace,
    BrainSpaceMember,
    BrainSpaceSource,
)
from app.models.item import Item
from app.models.recording import Recording
from app.models.user import User

Role = Literal["owner", "editor", "viewer"]

ROLE_RANK: dict[str, int] = {"viewer": 1, "editor": 2, "owner": 3}
ENGINE_PROFILES = {"waibrain", "obsidian", "gbrain", "mempalace"}
CLAIM_KINDS = {"fact", "decision", "principle", "workflow_rule", "open_question", "conflict"}
AUTO_ACCEPT_CONFIDENCE = 0.8


class BrainSpaceError(Exception):
    """Base service error for explicit route handling."""


class BrainSpaceNotFoundError(BrainSpaceError):
    """Space/resource not visible to this user."""


class BrainSpacePermissionError(BrainSpaceError):
    """User can see the Space but lacks the required role."""


class BrainSpaceValidationError(BrainSpaceError):
    """Invalid request payload."""


@dataclass
class SpaceAccess:
    space: BrainSpace
    role: Role


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (value or "").strip().lower()).strip("-")
    return slug or "space"


def _normalize_text(value: str) -> str:
    return " ".join((value or "").casefold().split())


def _dedup_key(space_id: uuid.UUID, kind: str, text: str) -> str:
    payload = f"{space_id}\x00{kind}\x00{_normalize_text(text)}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


async def _unique_slug(
    db: AsyncSession,
    *,
    table,
    owner_filter,
    base: str,
) -> str:
    slug = slugify(base)
    candidate = slug
    i = 2
    while True:
        exists = await db.scalar(select(table.id).where(owner_filter(candidate)).limit(1))
        if exists is None:
            return candidate
        candidate = f"{slug}-{i}"
        i += 1


async def create_space(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    name: str,
    kind: str = "personal",
    engine_profile: str = "waibrain",
    visibility: str = "private",
    description: str | None = None,
) -> BrainSpace:
    name = (name or "").strip()
    if not name:
        raise BrainSpaceValidationError("space name is required")
    if engine_profile not in ENGINE_PROFILES:
        raise BrainSpaceValidationError(f"unknown engine profile: {engine_profile}")

    slug = await _unique_slug(
        db,
        table=BrainSpace,
        owner_filter=lambda candidate: and_(
            BrainSpace.owner_user_id == user_id, BrainSpace.slug == candidate
        ),
        base=name,
    )
    space = BrainSpace(
        owner_user_id=user_id,
        name=name,
        slug=slug,
        kind=(kind or "personal").strip() or "personal",
        engine_profile=engine_profile,
        visibility=(visibility or "private").strip() or "private",
        description=(description or "").strip() or None,
    )
    db.add(space)
    await db.flush()
    db.add(
        BrainSpaceMember(
            space_id=space.id,
            user_id=user_id,
            role="owner",
            status="active",
            invited_by_user_id=user_id,
        )
    )
    await db.flush()
    return space


async def ensure_default_space(db: AsyncSession, user_id: uuid.UUID) -> BrainSpace:
    existing = (
        await db.execute(
            select(BrainSpace).where(
                BrainSpace.owner_user_id == user_id,
                BrainSpace.slug == "personal",
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    try:
        return await create_space(db, user_id, name="Personal", kind="personal")
    except IntegrityError:
        await db.rollback()
        existing_after_race = (
            await db.execute(
                select(BrainSpace).where(
                    BrainSpace.owner_user_id == user_id,
                    BrainSpace.slug == "personal",
                )
            )
        ).scalar_one_or_none()
        if existing_after_race is None:
            raise
        return existing_after_race


async def list_spaces_for_user(
    db: AsyncSession,
    user_id: uuid.UUID,
) -> list[tuple[BrainSpace, Role]]:
    await ensure_default_space(db, user_id)
    stmt = (
        select(BrainSpace, BrainSpaceMember.role)
        .join(BrainSpaceMember, BrainSpaceMember.space_id == BrainSpace.id)
        .where(
            BrainSpaceMember.user_id == user_id,
            BrainSpaceMember.status == "active",
        )
        .order_by(BrainSpace.created_at.asc(), BrainSpace.name.asc())
    )
    rows = list((await db.execute(stmt)).all())
    return [(space, role) for space, role in rows]


async def load_space_access(
    db: AsyncSession,
    user_id: uuid.UUID,
    space_id: uuid.UUID,
    *,
    min_role: str = "viewer",
) -> SpaceAccess:
    stmt = (
        select(BrainSpace, BrainSpaceMember.role)
        .join(BrainSpaceMember, BrainSpaceMember.space_id == BrainSpace.id)
        .where(
            BrainSpace.id == space_id,
            BrainSpaceMember.user_id == user_id,
            BrainSpaceMember.status == "active",
        )
    )
    row = (await db.execute(stmt)).one_or_none()
    if row is None:
        raise BrainSpaceNotFoundError("space not found")
    space, role = row
    if ROLE_RANK[role] < ROLE_RANK[min_role]:
        raise BrainSpacePermissionError(f"{min_role} role required")
    return SpaceAccess(space=space, role=role)


async def add_member(
    db: AsyncSession,
    *,
    actor_user_id: uuid.UUID,
    space_id: uuid.UUID,
    email: str,
    role: str,
) -> BrainSpaceMember:
    await load_space_access(db, actor_user_id, space_id, min_role="owner")
    if role not in ROLE_RANK or role == "owner":
        raise BrainSpaceValidationError("role must be viewer or editor")
    email = (email or "").strip().lower()
    if not email:
        raise BrainSpaceValidationError("email is required")
    user = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if user is None:
        raise BrainSpaceNotFoundError("user not found")

    existing = (
        await db.execute(
            select(BrainSpaceMember).where(
                BrainSpaceMember.space_id == space_id,
                BrainSpaceMember.user_id == user.id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        existing.role = role
        existing.status = "active"
        existing.invited_by_user_id = actor_user_id
        await db.flush()
        return existing

    member = BrainSpaceMember(
        space_id=space_id,
        user_id=user.id,
        role=role,
        status="active",
        invited_by_user_id=actor_user_id,
    )
    db.add(member)
    await db.flush()
    return member


def _frontmatter(space: BrainSpace, *, title: str, kind: str) -> dict[str, Any]:
    return {
        "wai_type": "brain_page",
        "space_id": str(space.id),
        "space_slug": space.slug,
        "engine_profile": space.engine_profile,
        "kind": kind,
        "title": title,
    }


def _render_frontmatter(frontmatter: dict[str, Any]) -> str:
    lines = ["---"]
    for key, value in frontmatter.items():
        lines.append(f"{key}: {value}")
    lines.append("---")
    return "\n".join(lines)


def _render_page_markdown(
    *,
    title: str,
    frontmatter: dict[str, Any],
    claims: list[BrainClaim] | None = None,
    body: str | None = None,
) -> str:
    parts = [_render_frontmatter(frontmatter), "", f"# {title}"]
    if body:
        stripped = body.strip()
        if stripped.startswith("---"):
            return stripped
        parts.extend(["", stripped])
    if claims:
        parts.extend(["", "## Claims"])
        for claim in claims:
            parts.append(
                f"- [{claim.kind}; {claim.status}; {claim.confidence:.2f}] {claim.text}"
            )
    return "\n".join(parts).strip()


def _validate_claim_input(claim: dict[str, Any]) -> tuple[str, str, float, str, list[Any]]:
    kind = str(claim.get("kind") or "").strip()
    if kind not in CLAIM_KINDS:
        raise BrainSpaceValidationError(f"unknown claim kind: {kind}")
    text = str(claim.get("text") or "").strip()
    if not text:
        raise BrainSpaceValidationError("claim text is required")
    confidence = float(claim.get("confidence", 0.5))
    if confidence < 0 or confidence > 1:
        raise BrainSpaceValidationError("claim confidence must be in [0,1]")
    authority = str(claim.get("authority") or "self").strip() or "self"
    evidence = claim.get("evidence")
    if evidence is None:
        evidence = []
    if not isinstance(evidence, list):
        raise BrainSpaceValidationError("claim evidence must be a list")
    return kind, text, confidence, authority, evidence


async def _create_claim(
    db: AsyncSession,
    *,
    space_id: uuid.UUID,
    page_id: uuid.UUID | None,
    actor_user_id: uuid.UUID | None,
    claim: dict[str, Any],
    default_evidence_title: str,
) -> BrainClaim:
    kind, text, confidence, authority, evidence = _validate_claim_input(claim)
    if not evidence and page_id is not None:
        evidence = [
            {
                "source_kind": "brain_page",
                "source_id": str(page_id),
                "title": default_evidence_title,
            }
        ]
    existing = (
        await db.execute(
            select(BrainClaim).where(
                BrainClaim.space_id == space_id,
                BrainClaim.dedup_key == _dedup_key(space_id, kind, text),
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    now = datetime.now(timezone.utc)
    brain_claim = BrainClaim(
        space_id=space_id,
        page_id=page_id,
        kind=kind,
        status=str(claim.get("status") or "active"),
        text=text,
        confidence=confidence,
        authority=authority,
        salience=claim.get("salience"),
        evidence=evidence,
        source_refs=claim.get("source_refs"),
        metadata_=claim.get("metadata"),
        dedup_key=_dedup_key(space_id, kind, text),
        accepted_by_user_id=actor_user_id,
        accepted_at=now,
    )
    db.add(brain_claim)
    await db.flush()
    return brain_claim


async def create_page(
    db: AsyncSession,
    *,
    actor_user_id: uuid.UUID,
    space_id: uuid.UUID,
    title: str,
    kind: str = "note",
    markdown: str | None = None,
    claims: list[dict[str, Any]] | None = None,
) -> BrainPage:
    access = await load_space_access(db, actor_user_id, space_id, min_role="editor")
    title = (title or "").strip()
    if not title:
        raise BrainSpaceValidationError("page title is required")
    kind = (kind or "note").strip() or "note"
    slug = await _unique_slug(
        db,
        table=BrainPage,
        owner_filter=lambda candidate: and_(
            BrainPage.space_id == space_id, BrainPage.slug == candidate
        ),
        base=title,
    )
    frontmatter = _frontmatter(access.space, title=title, kind=kind)
    page = BrainPage(
        space_id=space_id,
        title=title,
        slug=slug,
        kind=kind,
        status="active",
        markdown=markdown.strip() if markdown else _render_page_markdown(
            title=title, frontmatter=frontmatter
        ),
        frontmatter=frontmatter,
        created_by_user_id=actor_user_id,
        updated_by_user_id=actor_user_id,
    )
    db.add(page)
    await db.flush()

    created_claims: list[BrainClaim] = []
    for claim in claims or []:
        created_claims.append(
            await _create_claim(
                db,
                space_id=space_id,
                page_id=page.id,
                actor_user_id=actor_user_id,
                claim=claim,
                default_evidence_title=title,
            )
        )
    if not markdown:
        page.markdown = _render_page_markdown(
            title=title,
            frontmatter=frontmatter,
            claims=created_claims,
        )
    await db.flush()
    return page


async def get_page(db: AsyncSession, *, user_id: uuid.UUID, page_id: uuid.UUID) -> BrainPage:
    page = (await db.execute(select(BrainPage).where(BrainPage.id == page_id))).scalar_one_or_none()
    if page is None:
        raise BrainSpaceNotFoundError("page not found")
    await load_space_access(db, user_id, page.space_id)
    return page


async def list_pages(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    space_id: uuid.UUID,
) -> list[BrainPage]:
    await load_space_access(db, user_id, space_id)
    return list(
        (
            await db.execute(
                select(BrainPage)
                .where(BrainPage.space_id == space_id, BrainPage.status == "active")
                .order_by(BrainPage.updated_at.desc(), BrainPage.title.asc())
            )
        ).scalars().all()
    )


async def link_source(
    db: AsyncSession,
    *,
    actor_user_id: uuid.UUID,
    space_id: uuid.UUID,
    source_kind: str,
    source_id: uuid.UUID,
) -> BrainSpaceSource:
    await load_space_access(db, actor_user_id, space_id, min_role="editor")
    source_kind = (source_kind or "").strip()
    if source_kind == "item":
        source = (
            await db.execute(
                select(Item).where(
                    Item.id == source_id,
                    Item.user_id == actor_user_id,
                    Item.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        title = source.title or source.url or "Untitled" if source else None
        source_user_id = source.user_id if source else None
    elif source_kind == "recording":
        source = (
            await db.execute(
                select(Recording).where(
                    Recording.id == source_id,
                    Recording.user_id == actor_user_id,
                    Recording.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        title = source.title or "Untitled recording" if source else None
        source_user_id = source.user_id if source else None
    else:
        raise BrainSpaceValidationError("source_kind must be item or recording")
    if source is None or source_user_id is None:
        raise BrainSpaceNotFoundError("source not found")

    existing = (
        await db.execute(
            select(BrainSpaceSource).where(
                BrainSpaceSource.space_id == space_id,
                BrainSpaceSource.source_kind == source_kind,
                BrainSpaceSource.source_id == source_id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    linked = BrainSpaceSource(
        space_id=space_id,
        source_kind=source_kind,
        source_id=source_id,
        source_user_id=source_user_id,
        added_by_user_id=actor_user_id,
        source_title=title,
    )
    db.add(linked)
    await db.flush()
    return linked


async def build_home(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    space_id: uuid.UUID,
) -> dict[str, Any]:
    access = await load_space_access(db, user_id, space_id)
    claim_rows = (
        await db.execute(
            select(BrainClaim.kind, func.count())
            .where(BrainClaim.space_id == space_id, BrainClaim.status == "active")
            .group_by(BrainClaim.kind)
        )
    ).all()
    source_rows = (
        await db.execute(
            select(BrainSpaceSource.source_kind, func.count())
            .where(BrainSpaceSource.space_id == space_id)
            .group_by(BrainSpaceSource.source_kind)
        )
    ).all()
    pending_review_count = int(
        await db.scalar(
            select(func.count())
            .select_from(BrainReviewPack)
            .where(BrainReviewPack.space_id == space_id, BrainReviewPack.status == "pending")
        )
        or 0
    )
    page_count = int(
        await db.scalar(
            select(func.count())
            .select_from(BrainPage)
            .where(BrainPage.space_id == space_id, BrainPage.status == "active")
        )
        or 0
    )
    recent_pages = list(
        (
            await db.execute(
                select(BrainPage)
                .where(BrainPage.space_id == space_id, BrainPage.status == "active")
                .order_by(BrainPage.updated_at.desc(), BrainPage.created_at.desc())
                .limit(6)
            )
        ).scalars().all()
    )
    return {
        "space": access.space,
        "role": access.role,
        "page_count": page_count,
        "source_count": sum(int(count) for _, count in source_rows),
        "claim_counts": {kind: int(count) for kind, count in claim_rows},
        "source_counts": {kind: int(count) for kind, count in source_rows},
        "pending_review_count": pending_review_count,
        "recent_pages": recent_pages,
        "engine_profiles": sorted(ENGINE_PROFILES),
    }


async def list_review_packs(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    space_id: uuid.UUID,
    status: str | None = None,
) -> list[BrainReviewPack]:
    await load_space_access(db, user_id, space_id)
    stmt = select(BrainReviewPack).where(BrainReviewPack.space_id == space_id)
    if status is not None:
        stmt = stmt.where(BrainReviewPack.status == status)
    stmt = stmt.order_by(BrainReviewPack.created_at.desc(), BrainReviewPack.id.asc())
    return list((await db.execute(stmt)).scalars().all())


async def _get_or_create_page_for_claim(
    db: AsyncSession,
    *,
    actor_user_id: uuid.UUID,
    space_id: uuid.UUID,
    title: str,
    kind: str,
) -> BrainPage:
    slug = slugify(title)
    existing = (
        await db.execute(
            select(BrainPage).where(BrainPage.space_id == space_id, BrainPage.slug == slug)
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    return await create_page(
        db,
        actor_user_id=actor_user_id,
        space_id=space_id,
        title=title,
        kind=kind,
    )


async def accept_review_pack(
    db: AsyncSession,
    *,
    actor_user_id: uuid.UUID,
    space_id: uuid.UUID,
    pack_id: uuid.UUID,
) -> BrainReviewPack:
    await load_space_access(db, actor_user_id, space_id, min_role="owner")
    pack = (
        await db.execute(
            select(BrainReviewPack).where(
                BrainReviewPack.id == pack_id,
                BrainReviewPack.space_id == space_id,
            )
        )
    ).scalar_one_or_none()
    if pack is None:
        raise BrainSpaceNotFoundError("review pack not found")
    if pack.status != "pending":
        raise BrainSpaceValidationError(f"review pack is already {pack.status}")
    for proposal in pack.proposals:
        if not isinstance(proposal, dict) or proposal.get("type") != "claim":
            continue
        page = await _get_or_create_page_for_claim(
            db,
            actor_user_id=actor_user_id,
            space_id=space_id,
            title=str(proposal.get("page_title") or "Reviewed knowledge"),
            kind=str(proposal.get("page_kind") or "note"),
        )
        await _create_claim(
            db,
            space_id=space_id,
            page_id=page.id,
            actor_user_id=actor_user_id,
            claim=proposal,
            default_evidence_title=page.title,
        )
        page.markdown = _render_page_markdown(
            title=page.title,
            frontmatter=page.frontmatter,
            claims=list(
                (
                    await db.execute(
                        select(BrainClaim)
                        .where(BrainClaim.page_id == page.id, BrainClaim.status == "active")
                        .order_by(BrainClaim.created_at.asc())
                    )
                ).scalars().all()
            ),
        )
    pack.status = "accepted"
    pack.decided_by_user_id = actor_user_id
    pack.decided_at = datetime.now(timezone.utc)
    pack.decision_reason = "accepted by space owner"
    await db.flush()
    return pack


async def reject_review_pack(
    db: AsyncSession,
    *,
    actor_user_id: uuid.UUID,
    space_id: uuid.UUID,
    pack_id: uuid.UUID,
    reason: str | None = None,
) -> BrainReviewPack:
    await load_space_access(db, actor_user_id, space_id, min_role="owner")
    pack = (
        await db.execute(
            select(BrainReviewPack).where(
                BrainReviewPack.id == pack_id,
                BrainReviewPack.space_id == space_id,
            )
        )
    ).scalar_one_or_none()
    if pack is None:
        raise BrainSpaceNotFoundError("review pack not found")
    if pack.status != "pending":
        raise BrainSpaceValidationError(f"review pack is already {pack.status}")
    pack.status = "rejected"
    pack.decided_by_user_id = actor_user_id
    pack.decided_at = datetime.now(timezone.utc)
    pack.decision_reason = reason or "rejected by space owner"
    await db.flush()
    return pack


def _page_title_index(pages: list[BrainPage]) -> dict[str, BrainPage]:
    return {_normalize_text(page.title): page for page in pages}


async def match_spaces(
    db: AsyncSession,
    *,
    actor_user_id: uuid.UUID,
    target_space_id: uuid.UUID,
    other_space_id: uuid.UUID,
) -> BrainReviewPack:
    target = await load_space_access(db, actor_user_id, target_space_id, min_role="editor")
    other = await load_space_access(db, actor_user_id, other_space_id, min_role="viewer")
    target_pages = await list_pages(db, user_id=actor_user_id, space_id=target_space_id)
    other_pages = await list_pages(db, user_id=actor_user_id, space_id=other_space_id)
    target_index = _page_title_index(target_pages)

    proposals: list[dict[str, Any]] = []
    matched_titles: list[str] = []
    proposed_page_titles: list[str] = []
    for page in other_pages:
        target_page = target_index.get(_normalize_text(page.title))
        if target_page is not None:
            matched_titles.append(page.title)
            proposals.append(
                {
                    "type": "page_match",
                    "title": page.title,
                    "source_page_id": str(page.id),
                    "target_page_id": str(target_page.id),
                    "source_space_id": str(other.space.id),
                    "target_space_id": str(target.space.id),
                }
            )
        claims = list(
            (
                await db.execute(
                    select(BrainClaim).where(
                        BrainClaim.page_id == page.id,
                        BrainClaim.status == "active",
                    )
                )
            ).scalars().all()
        )
        for claim in claims:
            exists_in_target = await db.scalar(
                select(BrainClaim.id).where(
                    BrainClaim.space_id == target_space_id,
                    BrainClaim.dedup_key == _dedup_key(target_space_id, claim.kind, claim.text),
                )
            )
            if exists_in_target is not None:
                continue
            proposed_page_titles.append(page.title)
            proposals.append(
                {
                    "type": "claim",
                    "kind": claim.kind,
                    "text": claim.text,
                    "confidence": min(float(claim.confidence), 0.95),
                    "authority": "connected",
                    "page_title": page.title,
                    "page_kind": page.kind,
                    "evidence": [
                        {
                            "source_kind": "brain_space",
                            "source_id": str(other.space.id),
                            "title": other.space.name,
                            "page_id": str(page.id),
                        }
                    ],
                }
            )

    if matched_titles:
        summary = "Matched pages: " + ", ".join(sorted(set(matched_titles)))
    elif proposals:
        summary = (
            "Review pages: "
            + ", ".join(sorted(set(proposed_page_titles)))
            + f" from {other.space.name}."
        )
    else:
        summary = f"No reusable knowledge found from {other.space.name}."
    pack = BrainReviewPack(
        space_id=target_space_id,
        kind="bridge",
        risk="medium",
        status="pending",
        title=f"Bridge from {other.space.name}",
        summary=summary,
        proposals=proposals,
        evidence=[{"source_kind": "brain_space", "source_id": str(other.space.id)}],
        created_by_user_id=actor_user_id,
    )
    db.add(pack)
    await db.flush()
    return pack


async def build_context(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    space_id: uuid.UUID,
    task: str | None = None,
    limit: int = 80,
) -> dict[str, Any]:
    access = await load_space_access(db, user_id, space_id)
    claims = list(
        (
            await db.execute(
                select(BrainClaim, BrainPage.title)
                .outerjoin(BrainPage, BrainPage.id == BrainClaim.page_id)
                .where(BrainClaim.space_id == space_id, BrainClaim.status == "active")
                .order_by(BrainClaim.kind.asc(), BrainClaim.created_at.asc())
                .limit(limit)
            )
        ).all()
    )
    lines = [f"# {access.space.name} context"]
    if task:
        lines.extend(["", f"Task: {task.strip()}"])
    current_kind = None
    for claim, page_title in claims:
        if claim.kind != current_kind:
            current_kind = claim.kind
            lines.extend(["", f"## {claim.kind.replace('_', ' ').title()}"])
        source = f" ({page_title})" if page_title else ""
        lines.append(f"- {claim.text}{source}")
    return {
        "space": access.space,
        "markdown": "\n".join(lines).strip(),
        "claim_count": len(claims),
    }


async def export_space(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    space_id: uuid.UUID,
    profile: str,
) -> dict[str, Any]:
    access = await load_space_access(db, user_id, space_id)
    if profile not in ENGINE_PROFILES:
        raise BrainSpaceValidationError(f"unknown export profile: {profile}")
    pages = await list_pages(db, user_id=user_id, space_id=space_id)
    files = []
    for page in pages:
        path = f"{page.title}.md"
        if profile == "gbrain":
            path = f"compiled_truth/{page.slug}.md"
        elif profile == "mempalace":
            path = f"{access.space.name}/{page.kind}/{page.title}.md"
        files.append({"path": path, "markdown": page.markdown})
    return {"space": access.space, "profile": profile, "files": files}


def is_auto_eligible_claim(*, kind: str, confidence: float, authority: str) -> bool:
    return kind == "fact" and confidence >= AUTO_ACCEPT_CONFIDENCE and authority != "model"


async def propose_claim_review_pack(
    db: AsyncSession,
    *,
    actor_user_id: uuid.UUID,
    space_id: uuid.UUID,
    claim: dict[str, Any],
    page_title: str = "Reviewed knowledge",
) -> BrainReviewPack | BrainClaim:
    await load_space_access(db, actor_user_id, space_id, min_role="editor")
    kind, text, confidence, authority, evidence = _validate_claim_input(claim)
    proposal = {
        "type": "claim",
        "kind": kind,
        "text": text,
        "confidence": confidence,
        "authority": authority,
        "page_title": page_title,
        "evidence": evidence,
    }
    if is_auto_eligible_claim(kind=kind, confidence=confidence, authority=authority):
        page = await _get_or_create_page_for_claim(
            db,
            actor_user_id=actor_user_id,
            space_id=space_id,
            title=page_title,
            kind="note",
        )
        return await _create_claim(
            db,
            space_id=space_id,
            page_id=page.id,
            actor_user_id=actor_user_id,
            claim=proposal,
            default_evidence_title=page.title,
        )
    pack = BrainReviewPack(
        space_id=space_id,
        kind="claim",
        risk="high" if kind != "fact" else "medium",
        status="pending",
        title=f"Review {kind.replace('_', ' ')}",
        summary=f"{kind}: {text}",
        proposals=[proposal],
        evidence=evidence,
        created_by_user_id=actor_user_id,
    )
    db.add(pack)
    await db.flush()
    return pack
