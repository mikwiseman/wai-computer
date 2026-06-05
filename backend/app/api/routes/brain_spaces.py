"""HTTP routes for WaiBrain Spaces."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import CurrentUser, Database
from app.core.brain_spaces import (
    BrainSpaceNotFoundError,
    BrainSpacePermissionError,
    BrainSpaceValidationError,
    accept_review_pack,
    add_member,
    build_context,
    build_home,
    create_page,
    create_space,
    export_space,
    link_source,
    list_pages,
    list_review_packs,
    list_spaces_for_user,
    match_spaces,
    reject_review_pack,
)
from app.models.brain_space import (
    BrainClaim,
    BrainPage,
    BrainReviewPack,
    BrainSpace,
    BrainSpaceSource,
)

router = APIRouter(prefix="/brain/spaces", tags=["brain-spaces"])


class CreateSpaceRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    kind: str = Field(default="personal", max_length=40)
    engine_profile: str = Field(default="waibrain", max_length=40)
    visibility: str = Field(default="private", max_length=40)
    description: str | None = None


class LinkSourceRequest(BaseModel):
    source_kind: str = Field(max_length=30)
    source_id: UUID


class ClaimRequest(BaseModel):
    kind: str
    text: str
    confidence: float = 0.5
    authority: str = "self"
    evidence: list[dict[str, Any]] | None = None
    salience: float | None = None
    source_refs: list[dict[str, Any]] | None = None
    metadata: dict[str, Any] | None = None


class CreatePageRequest(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    kind: str = Field(default="note", max_length=40)
    markdown: str | None = None
    claims: list[ClaimRequest] = Field(default_factory=list)


class AddMemberRequest(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    role: str = Field(max_length=20)


class MatchSpacesRequest(BaseModel):
    other_space_id: UUID


class ContextRequest(BaseModel):
    task: str | None = None
    limit: int = Field(default=80, ge=1, le=500)


class RejectReviewPackRequest(BaseModel):
    reason: str | None = None


def _raise_http(exc: Exception) -> None:
    if isinstance(exc, BrainSpaceNotFoundError):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    if isinstance(exc, BrainSpacePermissionError):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    if isinstance(exc, BrainSpaceValidationError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    raise exc


def _space_response(space: BrainSpace, *, role: str | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {
        "id": str(space.id),
        "owner_user_id": str(space.owner_user_id),
        "name": space.name,
        "slug": space.slug,
        "kind": space.kind,
        "engine_profile": space.engine_profile,
        "visibility": space.visibility,
        "description": space.description,
        "metadata": space.metadata_ or {},
        "created_at": space.created_at.isoformat() if space.created_at else None,
        "updated_at": space.updated_at.isoformat() if space.updated_at else None,
    }
    if role is not None:
        body["role"] = role
    return body


def _claim_response(claim: BrainClaim) -> dict[str, Any]:
    return {
        "id": str(claim.id),
        "space_id": str(claim.space_id),
        "page_id": str(claim.page_id) if claim.page_id else None,
        "kind": claim.kind,
        "status": claim.status,
        "text": claim.text,
        "confidence": claim.confidence,
        "authority": claim.authority,
        "salience": claim.salience,
        "evidence": claim.evidence,
        "source_refs": claim.source_refs or [],
        "metadata": claim.metadata_ or {},
    }


def _space_source_response(source: BrainSpaceSource) -> dict[str, Any]:
    return {
        "id": str(source.id),
        "space_id": str(source.space_id),
        "source_kind": source.source_kind,
        "source_id": str(source.source_id),
        "source_title": source.source_title,
        "created_at": source.created_at.isoformat() if source.created_at else None,
    }


async def _claims_for_page(db: Database, page: BrainPage) -> list[BrainClaim]:
    return list(
        (
            await db.execute(
                select(BrainClaim)
                .where(BrainClaim.page_id == page.id)
                .order_by(BrainClaim.created_at.asc(), BrainClaim.id.asc())
            )
        ).scalars().all()
    )


async def _page_response(db: Database, page: BrainPage) -> dict[str, Any]:
    claims = await _claims_for_page(db, page)
    return {
        "id": str(page.id),
        "space_id": str(page.space_id),
        "title": page.title,
        "slug": page.slug,
        "kind": page.kind,
        "status": page.status,
        "markdown": page.markdown,
        "frontmatter": page.frontmatter,
        "version": page.version,
        "claims": [_claim_response(claim) for claim in claims],
        "created_at": page.created_at.isoformat() if page.created_at else None,
        "updated_at": page.updated_at.isoformat() if page.updated_at else None,
    }


def _review_pack_response(pack: BrainReviewPack) -> dict[str, Any]:
    return {
        "id": str(pack.id),
        "space_id": str(pack.space_id),
        "kind": pack.kind,
        "risk": pack.risk,
        "status": pack.status,
        "title": pack.title,
        "summary": pack.summary,
        "proposals": pack.proposals,
        "evidence": pack.evidence or [],
        "created_by_user_id": (
            str(pack.created_by_user_id) if pack.created_by_user_id else None
        ),
        "decided_by_user_id": (
            str(pack.decided_by_user_id) if pack.decided_by_user_id else None
        ),
        "created_at": pack.created_at.isoformat() if pack.created_at else None,
        "decided_at": pack.decided_at.isoformat() if pack.decided_at else None,
        "decision_reason": pack.decision_reason,
    }


@router.get("")
async def list_spaces(user: CurrentUser, db: Database) -> dict[str, Any]:
    try:
        spaces = await list_spaces_for_user(db, user.id)
    except Exception as exc:  # noqa: BLE001 - translated by type below.
        _raise_http(exc)
    return {
        "spaces": [
            _space_response(space, role=role)
            for space, role in spaces
        ]
    }


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_brain_space(
    request: CreateSpaceRequest,
    user: CurrentUser,
    db: Database,
) -> dict[str, Any]:
    try:
        space = await create_space(
            db,
            user.id,
            name=request.name,
            kind=request.kind,
            engine_profile=request.engine_profile,
            visibility=request.visibility,
            description=request.description,
        )
    except Exception as exc:  # noqa: BLE001 - translated by type below.
        _raise_http(exc)
    return _space_response(space, role="owner")


@router.post("/{space_id}/sources", status_code=status.HTTP_201_CREATED)
async def add_space_source(
    space_id: UUID,
    request: LinkSourceRequest,
    user: CurrentUser,
    db: Database,
) -> dict[str, Any]:
    try:
        source = await link_source(
            db,
            actor_user_id=user.id,
            space_id=space_id,
            source_kind=request.source_kind,
            source_id=request.source_id,
        )
    except Exception as exc:  # noqa: BLE001 - translated by type below.
        _raise_http(exc)
    return _space_source_response(source)


@router.post("/{space_id}/pages", status_code=status.HTTP_201_CREATED)
async def create_space_page(
    space_id: UUID,
    request: CreatePageRequest,
    user: CurrentUser,
    db: Database,
) -> dict[str, Any]:
    try:
        page = await create_page(
            db,
            actor_user_id=user.id,
            space_id=space_id,
            title=request.title,
            kind=request.kind,
            markdown=request.markdown,
            claims=[claim.model_dump(exclude_none=True) for claim in request.claims],
        )
    except Exception as exc:  # noqa: BLE001 - translated by type below.
        _raise_http(exc)
    return await _page_response(db, page)


@router.get("/{space_id}/pages")
async def list_space_pages(
    space_id: UUID,
    user: CurrentUser,
    db: Database,
) -> dict[str, Any]:
    try:
        pages = await list_pages(db, user_id=user.id, space_id=space_id)
    except Exception as exc:  # noqa: BLE001 - translated by type below.
        _raise_http(exc)
    return {"pages": [await _page_response(db, page) for page in pages]}


@router.get("/{space_id}/home")
async def get_space_home(
    space_id: UUID,
    user: CurrentUser,
    db: Database,
) -> dict[str, Any]:
    try:
        home = await build_home(db, user_id=user.id, space_id=space_id)
    except Exception as exc:  # noqa: BLE001 - translated by type below.
        _raise_http(exc)
    return {
        **home,
        "space": _space_response(home["space"], role=home["role"]),
        "recent_pages": [
            await _page_response(db, page)
            for page in home["recent_pages"]
        ],
        "sources": [_space_source_response(source) for source in home["sources"]],
    }


@router.get("/{space_id}/export")
async def export_brain_space(
    space_id: UUID,
    user: CurrentUser,
    db: Database,
    profile: str = Query(default="waibrain"),
) -> dict[str, Any]:
    try:
        exported = await export_space(
            db,
            user_id=user.id,
            space_id=space_id,
            profile=profile,
        )
    except Exception as exc:  # noqa: BLE001 - translated by type below.
        _raise_http(exc)
    return {
        **exported,
        "space": _space_response(exported["space"]),
    }


@router.post("/{space_id}/members", status_code=status.HTTP_201_CREATED)
async def add_space_member(
    space_id: UUID,
    request: AddMemberRequest,
    user: CurrentUser,
    db: Database,
) -> dict[str, Any]:
    try:
        member = await add_member(
            db,
            actor_user_id=user.id,
            space_id=space_id,
            email=str(request.email),
            role=request.role,
        )
    except Exception as exc:  # noqa: BLE001 - translated by type below.
        _raise_http(exc)
    return {
        "id": str(member.id),
        "space_id": str(member.space_id),
        "user_id": str(member.user_id),
        "role": member.role,
        "status": member.status,
    }


@router.post("/{space_id}/match", status_code=status.HTTP_201_CREATED)
async def create_space_match(
    space_id: UUID,
    request: MatchSpacesRequest,
    user: CurrentUser,
    db: Database,
) -> dict[str, Any]:
    try:
        pack = await match_spaces(
            db,
            actor_user_id=user.id,
            target_space_id=space_id,
            other_space_id=request.other_space_id,
        )
    except Exception as exc:  # noqa: BLE001 - translated by type below.
        _raise_http(exc)
    return _review_pack_response(pack)


@router.get("/{space_id}/review-packs")
async def get_review_packs(
    space_id: UUID,
    user: CurrentUser,
    db: Database,
    status_filter: str | None = Query(default=None, alias="status"),
) -> dict[str, Any]:
    try:
        packs = await list_review_packs(
            db,
            user_id=user.id,
            space_id=space_id,
            status=status_filter,
        )
    except Exception as exc:  # noqa: BLE001 - translated by type below.
        _raise_http(exc)
    return {
        "review_packs": [_review_pack_response(pack) for pack in packs],
        "pending_count": sum(1 for pack in packs if pack.status == "pending"),
    }


@router.post("/{space_id}/review-packs/{pack_id}/accept")
async def accept_space_review_pack(
    space_id: UUID,
    pack_id: UUID,
    user: CurrentUser,
    db: Database,
) -> dict[str, Any]:
    try:
        pack = await accept_review_pack(
            db,
            actor_user_id=user.id,
            space_id=space_id,
            pack_id=pack_id,
        )
    except Exception as exc:  # noqa: BLE001 - translated by type below.
        _raise_http(exc)
    return _review_pack_response(pack)


@router.post("/{space_id}/review-packs/{pack_id}/reject")
async def reject_space_review_pack(
    space_id: UUID,
    pack_id: UUID,
    request: RejectReviewPackRequest,
    user: CurrentUser,
    db: Database,
) -> dict[str, Any]:
    try:
        pack = await reject_review_pack(
            db,
            actor_user_id=user.id,
            space_id=space_id,
            pack_id=pack_id,
            reason=request.reason,
        )
    except Exception as exc:  # noqa: BLE001 - translated by type below.
        _raise_http(exc)
    return _review_pack_response(pack)


@router.post("/{space_id}/context")
async def build_space_context(
    space_id: UUID,
    request: ContextRequest,
    user: CurrentUser,
    db: Database,
) -> dict[str, Any]:
    try:
        context = await build_context(
            db,
            user_id=user.id,
            space_id=space_id,
            task=request.task,
            limit=request.limit,
        )
    except Exception as exc:  # noqa: BLE001 - translated by type below.
        _raise_http(exc)
    return {
        **context,
        "space": _space_response(context["space"]),
    }
