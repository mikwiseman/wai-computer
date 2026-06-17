"""Schemes routes — product-facing infinite boards over Brain Map projections."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.api.deps import CurrentUser, Database
from app.core.brain_maps import (
    BrainMapError,
    BrainMapNotFoundError,
    BrainMapValidationError,
    create_brain_map,
    list_brain_maps,
    load_brain_map,
    refresh_brain_map,
    update_brain_map,
)
from app.models.brain_map import BrainMap, BrainMapRevision

router = APIRouter(prefix="/schemes", tags=["schemes"])

SCHEME_LAYOUT_VERSION = 2
SCHEME_SHAPE_KINDS = {"rectangle", "ellipse"}


class SchemePosition(BaseModel):
    x: float
    y: float


class SchemeViewport(BaseModel):
    x: float = 0
    y: float = 0
    zoom: float = Field(default=1, gt=0, le=4)


class SchemeStroke(BaseModel):
    id: str = Field(min_length=1)
    points: list[SchemePosition] = Field(min_length=2)
    color: str = Field(default="#111827", min_length=1, max_length=40)
    width: float = Field(default=3, gt=0, le=40)


class SchemeCanvasCard(BaseModel):
    id: str = Field(min_length=1)
    x: float
    y: float
    width: float = Field(gt=20, le=1200)
    height: float = Field(gt=20, le=1200)
    text: str = Field(min_length=1, max_length=2000)
    color: str = Field(default="#f7d774", min_length=1, max_length=40)


class SchemeCanvasShape(BaseModel):
    id: str = Field(min_length=1)
    kind: str = Field(min_length=1, max_length=40)
    x: float
    y: float
    width: float = Field(gt=10, le=2000)
    height: float = Field(gt=10, le=2000)
    color: str = Field(default="#2563eb", min_length=1, max_length=40)
    fill: str = Field(default="transparent", min_length=1, max_length=40)


class SchemeConnector(BaseModel):
    id: str = Field(min_length=1)
    source_id: str | None = Field(default=None, min_length=1)
    target_id: str | None = Field(default=None, min_length=1)
    points: list[SchemePosition] = Field(default_factory=list)
    label: str | None = Field(default=None, max_length=300)
    color: str = Field(default="#475569", min_length=1, max_length=40)


class SchemeCanvasLayout(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = SCHEME_LAYOUT_VERSION
    viewport: SchemeViewport = Field(default_factory=SchemeViewport)
    node_positions: dict[str, SchemePosition] = Field(default_factory=dict)
    strokes: list[SchemeStroke] = Field(default_factory=list)
    cards: list[SchemeCanvasCard] = Field(default_factory=list)
    shapes: list[SchemeCanvasShape] = Field(default_factory=list)
    connectors: list[SchemeConnector] = Field(default_factory=list)

    @classmethod
    def validate_shape_kinds(cls, layout: "SchemeCanvasLayout") -> "SchemeCanvasLayout":
        for shape in layout.shapes:
            if shape.kind not in SCHEME_SHAPE_KINDS:
                raise ValueError(f"Unsupported scheme shape kind: {shape.kind}")
        return layout


class SchemeRevisionResponse(BaseModel):
    id: str
    scheme_id: str
    revision_index: int
    projection: dict[str, Any]
    source_fingerprint: str
    source_count: int
    freshness: dict[str, Any]
    diff: dict[str, Any]
    citations: list[dict[str, Any]]
    compiled_at: datetime
    created_at: datetime


class SchemeResponse(BaseModel):
    id: str
    space_id: str | None
    title: str
    prompt: str
    scheme_type: str
    origin: str
    status: str
    source_scope: dict[str, Any] | None
    layout: SchemeCanvasLayout | None
    current_revision_id: str | None
    current_revision: SchemeRevisionResponse | None
    created_at: datetime
    updated_at: datetime


class SchemesResponse(BaseModel):
    schemes: list[SchemeResponse]


class SchemeCreateRequest(BaseModel):
    prompt: str
    origin: str = "brain"
    scheme_type: str | None = None
    title: str | None = None
    space_id: UUID | None = None
    source_scope: dict[str, Any] | None = None


class SchemeUpdateRequest(BaseModel):
    title: str | None = None
    status: str | None = None
    layout: dict[str, Any] | None = Field(default=None)


def _raise_scheme_http(exc: Exception) -> None:
    if isinstance(exc, BrainMapNotFoundError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Scheme not found"
        ) from exc
    if isinstance(exc, BrainMapValidationError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    if isinstance(exc, BrainMapError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    raise exc


def _is_position(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and isinstance(value.get("x"), int | float)
        and isinstance(value.get("y"), int | float)
    )


def _is_legacy_position_map(layout: dict[str, Any]) -> bool:
    return "version" not in layout and all(_is_position(value) for value in layout.values())


def _normalise_canvas_layout(layout: dict[str, Any] | None) -> SchemeCanvasLayout | None:
    if layout is None:
        return None
    payload = {"node_positions": layout} if _is_legacy_position_map(layout) else layout
    try:
        normalised = SchemeCanvasLayout.model_validate(payload)
        return SchemeCanvasLayout.validate_shape_kinds(normalised)
    except (ValidationError, ValueError) as exc:
        raise BrainMapValidationError(f"Invalid scheme layout: {exc}") from exc


def _layout_payload(layout: dict[str, Any] | None) -> dict[str, Any] | None:
    normalised = _normalise_canvas_layout(layout)
    return normalised.model_dump(mode="json") if normalised else None


def _projection_with_scheme_layout(
    projection: dict[str, Any],
    layout: dict[str, Any] | None,
) -> dict[str, Any]:
    next_projection = deepcopy(projection)
    if "map_type" in next_projection and "scheme_type" not in next_projection:
        next_projection["scheme_type"] = next_projection["map_type"]

    canvas_layout = _normalise_canvas_layout(layout)
    layout_by_node = canvas_layout.node_positions if canvas_layout else {}
    nodes = next_projection.get("nodes")
    if not isinstance(nodes, list):
        return next_projection

    for node in nodes:
        if not isinstance(node, dict):
            continue
        node_id = node.get("id")
        if not isinstance(node_id, str):
            continue
        position = layout_by_node.get(node_id)
        if position:
            node["position"] = position.model_dump()
    return next_projection


def _revision_response(
    revision: BrainMapRevision,
    *,
    layout: dict[str, Any] | None,
) -> SchemeRevisionResponse:
    return SchemeRevisionResponse(
        id=str(revision.id),
        scheme_id=str(revision.map_id),
        revision_index=revision.revision_index,
        projection=_projection_with_scheme_layout(revision.projection, layout),
        source_fingerprint=revision.source_fingerprint,
        source_count=revision.source_count,
        freshness=revision.freshness,
        diff=revision.diff,
        citations=revision.citations,
        compiled_at=revision.compiled_at,
        created_at=revision.created_at,
    )


def _scheme_response(
    brain_map: BrainMap,
    revision: BrainMapRevision | None,
) -> SchemeResponse:
    return SchemeResponse(
        id=str(brain_map.id),
        space_id=str(brain_map.space_id) if brain_map.space_id else None,
        title=brain_map.title,
        prompt=brain_map.prompt,
        scheme_type=brain_map.map_type,
        origin=brain_map.origin,
        status=brain_map.status,
        source_scope=brain_map.source_scope,
        layout=_normalise_canvas_layout(brain_map.layout),
        current_revision_id=(
            str(brain_map.current_revision_id) if brain_map.current_revision_id else None
        ),
        current_revision=(
            _revision_response(revision, layout=brain_map.layout) if revision else None
        ),
        created_at=brain_map.created_at,
        updated_at=brain_map.updated_at,
    )


@router.get("", response_model=SchemesResponse)
async def list_schemes(
    user: CurrentUser,
    db: Database,
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(50, ge=1, le=200),
) -> SchemesResponse:
    rows = await list_brain_maps(db, user.id, status=status_filter, limit=limit)
    return SchemesResponse(schemes=[_scheme_response(brain_map, rev) for brain_map, rev in rows])


@router.post("", response_model=SchemeResponse, status_code=status.HTTP_201_CREATED)
async def create_scheme(
    request: SchemeCreateRequest,
    user: CurrentUser,
    db: Database,
) -> SchemeResponse:
    try:
        brain_map, revision = await create_brain_map(
            db,
            user.id,
            prompt=request.prompt,
            origin=request.origin,
            map_type=request.scheme_type,
            title=request.title,
            space_id=request.space_id,
            source_scope=request.source_scope,
        )
    except Exception as exc:  # noqa: BLE001 - translated by type.
        _raise_scheme_http(exc)
    return _scheme_response(brain_map, revision)


@router.get("/{scheme_id}", response_model=SchemeResponse)
async def get_scheme(
    scheme_id: UUID,
    user: CurrentUser,
    db: Database,
) -> SchemeResponse:
    try:
        brain_map, revision = await load_brain_map(db, user.id, scheme_id)
    except Exception as exc:  # noqa: BLE001 - translated by type.
        _raise_scheme_http(exc)
    return _scheme_response(brain_map, revision)


@router.patch("/{scheme_id}", response_model=SchemeResponse)
async def update_scheme(
    scheme_id: UUID,
    request: SchemeUpdateRequest,
    user: CurrentUser,
    db: Database,
) -> SchemeResponse:
    try:
        layout = _layout_payload(request.layout) if "layout" in request.model_fields_set else None
        brain_map, revision = await update_brain_map(
            db,
            user.id,
            scheme_id,
            title=request.title,
            status=request.status,
            layout=layout,
        )
    except Exception as exc:  # noqa: BLE001 - translated by type.
        _raise_scheme_http(exc)
    return _scheme_response(brain_map, revision)


@router.post("/{scheme_id}/refresh", response_model=SchemeRevisionResponse)
async def refresh_scheme(
    scheme_id: UUID,
    user: CurrentUser,
    db: Database,
) -> SchemeRevisionResponse:
    try:
        revision = await refresh_brain_map(db, user.id, scheme_id)
        brain_map, _current = await load_brain_map(db, user.id, scheme_id)
    except Exception as exc:  # noqa: BLE001 - translated by type.
        _raise_scheme_http(exc)
    return _revision_response(revision, layout=brain_map.layout)
