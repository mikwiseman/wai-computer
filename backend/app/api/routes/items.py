"""Universal item routes — "add anything" capture + the unified feed.

``POST /items`` is the signal-capture-first intake for non-audio content
(pasted text, an article URL, a forwarded link). It stores the raw item
immediately, embeds it, and enqueues background summarization (summary +
key-moments table). Re-posting the same content/URL is idempotent.

``GET /items`` is the item half of the unified feed (filterable by source /
kind / folder). ``GET /items/{id}`` returns the item with its summary and the
hero key-moments table.

Note: source fetching for URLs (YouTube/article/PDF) lands in a follow-up; for
now a URL with no body is stored as a raw item and a body can be supplied
(e.g. by a fetcher or the Telegram path). No silent fallback — an empty
paste is rejected.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from fastapi import (
    APIRouter,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import inspect, select
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentUser, Database
from app.api.summary_audio import (
    SummaryAudioResponse,
    serialize_summary_audio,
    summary_audio_file_response,
)
from app.core.document_extract import (
    SUPPORTED_DOCUMENT_EXTENSIONS,
    DocumentExtractionError,
    document_kind_for_extension,
    extract_document_text,
    resolve_document_extension,
)
from app.core.item_ingest import enqueue_item_processing, ingest_item
from app.core.item_titles import clean_title, title_from_body, title_from_filename
from app.core.summary_audio import (
    SUMMARY_AUDIO_SOURCE_ITEM,
    SummaryAudioError,
    build_item_summary_audio_text,
    latest_summary_audio_artifact_for_hash,
    load_latest_summary_audio_artifact,
    start_summary_audio_artifact,
    summary_audio_hash,
)
from app.models.item import Item, ItemSummary
from app.models.recording import Folder, Recording, RecordingStatus
from app.models.summary_audio import SummaryAudioStatus

router = APIRouter(prefix="/items", tags=["items"])

logger = logging.getLogger(__name__)


async def _require_folder(
    folder_id: UUID | None,
    user_id: UUID,
    db: Database,
) -> Folder | None:
    if folder_id is None:
        return None
    result = await db.execute(
        select(Folder).where(Folder.id == folder_id, Folder.user_id == user_id)
    )
    folder = result.scalar_one_or_none()
    if folder is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Folder not found")
    return folder


class CreateItemRequest(BaseModel):
    """Add anything to the brain: a paste, a URL, or fetched content."""

    source: str = Field(default="paste", max_length=80)
    kind: str = Field(default="note", max_length=50)
    title: str | None = Field(default=None, max_length=500)
    body: str | None = None
    url: str | None = Field(default=None, max_length=2000)
    folder_id: UUID | None = None


class ItemSummaryResponse(BaseModel):
    summary: str | None
    key_points: list[Any] | None
    action_items: list[Any] | None
    topics: list[Any] | None
    people_mentioned: list[Any] | None
    highlights: list[Any] | None
    key_moments: list[Any] | None
    sentiment: str | None


class ItemError(BaseModel):
    """A user-facing reason an item could not be fetched or processed."""

    code: str
    message: str


class ItemResponse(BaseModel):
    id: str
    source: str
    source_ref: str | None
    url: str | None
    kind: str
    title: str | None
    body: str | None
    occurred_at: str | None
    state: str
    # Derived processing status the client can render directly:
    # fetching | summarizing | ready | needs_input | failed.
    status: str
    error: ItemError | None = None
    folder_id: str | None
    created_at: str
    summary: ItemSummaryResponse | None = None
    summary_audio: SummaryAudioResponse | None = None


class ItemListEntry(BaseModel):
    id: str
    source: str
    url: str | None
    kind: str
    title: str | None
    state: str
    status: str
    error: ItemError | None = None
    folder_id: str | None
    occurred_at: str | None
    created_at: str
    has_summary: bool


class ItemListResponse(BaseModel):
    items: list[ItemListEntry]
    total: int


def _summary_response(summary: ItemSummary | None) -> ItemSummaryResponse | None:
    if summary is None:
        return None
    return ItemSummaryResponse(
        summary=summary.summary,
        key_points=summary.key_points,
        action_items=summary.action_items,
        topics=summary.topics,
        people_mentioned=summary.people_mentioned,
        highlights=summary.highlights,
        key_moments=summary.key_moments,
        sentiment=summary.sentiment,
    )


def _item_error(item: Item) -> ItemError | None:
    """Surface the stored fetch/processing error (no-fallback: visible to clients)."""
    meta = item.metadata_ or {}
    err = meta.get("fetch_error") or meta.get("processing_error")
    if not isinstance(err, dict):
        return None
    return ItemError(
        code=str(err.get("code") or "error"),
        message=str(err.get("message") or ""),
    )


def _derive_status(item: Item, has_summary: bool, *, has_body: bool | None = None) -> str:
    """Derive a client-facing processing status from the item's state + data.

    Honest statuses only: ``needs_input`` (a recoverable fetch error the user
    can resolve), ``failed`` (processing could not start), ``ready`` (summary
    present), ``fetching`` (URL awaiting its background fetch), ``summarizing``
    (body present, summary pending).

    ``has_body`` lets list queries pass a SQL-computed flag so the full body
    text (whole articles/PDFs) never leaves the database for feed pages.
    """
    if item.state == "needs_input":
        return "needs_input"
    meta = item.metadata_ or {}
    if item.state == "failed" or meta.get("processing_error"):
        return "failed"
    if has_summary:
        return "ready"
    body_present = (
        has_body if has_body is not None else bool((item.body or "").strip())
    )
    if not body_present and (item.url or "").strip():
        return "fetching"
    return "summarizing"


def _item_response(item: Item, summary: ItemSummary | None) -> ItemResponse:
    audio_text = build_item_summary_audio_text(summary)
    audio_hash = summary_audio_hash(audio_text) if audio_text else None
    loaded_artifacts = (
        []
        if "summary_audio_artifacts" in inspect(item).unloaded
        else list(getattr(item, "summary_audio_artifacts", []) or [])
    )
    audio_artifact = (
        latest_summary_audio_artifact_for_hash(
            loaded_artifacts,
            audio_hash,
        )
        if audio_hash
        else None
    )
    return ItemResponse(
        id=str(item.id),
        source=item.source,
        source_ref=item.source_ref,
        url=item.url,
        kind=item.kind,
        title=item.title or title_from_body(item.body),
        body=item.body,
        occurred_at=item.occurred_at.isoformat() if item.occurred_at else None,
        state=item.state,
        status=_derive_status(item, summary is not None),
        error=_item_error(item),
        folder_id=str(item.folder_id) if item.folder_id else None,
        created_at=item.created_at.isoformat(),
        summary=_summary_response(summary),
        summary_audio=serialize_summary_audio(
            source_kind=SUMMARY_AUDIO_SOURCE_ITEM,
            source_id=item.id,
            artifact=audio_artifact,
            audio_url=f"/api/items/{item.id}/summary/audio/file",
        ),
    )


async def _enqueue_item_summary(db: Database, item: Item) -> None:
    """Enqueue background summarization (shared with the MCP ``remember`` tool)."""
    await enqueue_item_processing(db, item)


def enqueue_summary_audio_generation(artifact_id: UUID) -> str:
    from app.tasks.celery_app import celery_app

    result = celery_app.send_task(
        "app.tasks.summary_audio_generation.generate_summary_audio",
        kwargs={"artifact_id": str(artifact_id)},
    )
    return str(result.id)


@router.post("", response_model=ItemResponse, status_code=status.HTTP_201_CREATED)
async def create_item(
    request: CreateItemRequest,
    user: CurrentUser,
    db: Database,
) -> ItemResponse:
    """Add anything to the brain. Stores immediately, summarizes in background."""
    has_body = bool((request.body or "").strip())
    has_url = bool((request.url or "").strip())
    if not has_body and not has_url:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide body text or a URL.",
        )
    folder = await _require_folder(request.folder_id, user.id, db)

    # Stable dedup key: prefer the URL (stable before/after fetch), else body.
    dedup_key = request.url if has_url else request.body

    item, created = await ingest_item(
        db,
        user.id,
        source=request.source,
        kind=request.kind,
        title=request.title,
        body=request.body,
        url=request.url,
        folder_id=folder.id if folder else None,
        dedup_key=dedup_key,
        embed=has_body,
    )
    await db.flush()

    if created:
        # Fetch (if URL-only), embed, summarize + key-moments — in the worker.
        await _enqueue_item_summary(db, item)

    summary = (
        await db.execute(select(ItemSummary).where(ItemSummary.item_id == item.id))
    ).scalar_one_or_none()
    return _item_response(item, summary)


# --- File upload: documents -> Item (sync), audio/video -> Recording (async) -
# One "add anything" endpoint routes by type: readable documents are extracted
# inline into an Item; audio/video are staged to disk and handed to the
# recording pipeline (import_media_as_recording: ffmpeg normalise + transcribe)
# via a Celery task, since that work is too slow to run in the request.
_UPLOAD_CHUNK = 1024 * 1024


def _media_upload_ext(filename: str | None, content_type: str | None) -> str:
    """Resolve a supported audio/video extension, or "" if this isn't media."""
    from app.core.recording_import import RecordingImportError, resolve_import_extension

    try:
        return resolve_import_extension(filename, content_type)
    except RecordingImportError:
        return ""


async def _stage_media_upload(
    user_id: Any, ext: str, file: UploadFile, max_bytes: int
) -> tuple[Path, int]:
    """Stream an uploaded media file straight to a UUID-keyed staging path
    (never buffered whole in memory — video can be large), enforcing the size
    cap as we go. Returns (path, bytes_written)."""
    from app.config import get_settings

    base = Path(get_settings().upload_staging_dir) / "items" / str(user_id)
    base.mkdir(parents=True, exist_ok=True)
    path = base / f"{uuid4().hex}.{ext}"
    size = 0
    try:
        with path.open("wb") as fh:
            while True:
                chunk = await file.read(_UPLOAD_CHUNK)
                if not chunk:
                    break
                size += len(chunk)
                if size > max_bytes:
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail=f"File too large. Maximum size is {max_bytes // (1024 * 1024)}MB.",
                    )
                fh.write(chunk)
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return path, size


async def _handle_media_upload(
    user: Any,
    db: Database,
    ext: str,
    file: UploadFile,
    title: str | None,
    folder_id: UUID | None,
) -> JSONResponse:
    """Stage an audio/video upload and enqueue background transcription. Returns
    202 with the Recording id so clients can select the processing row immediately."""
    from app.config import get_settings

    filename, content_type, language = file.filename, file.content_type, user.default_language
    try:
        staged, size = await _stage_media_upload(
            user.id, ext, file, get_settings().upload_max_bytes
        )
    finally:
        await file.close()
    if size == 0:
        staged.unlink(missing_ok=True)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Empty file.")

    user_title = clean_title(title)
    display_title = user_title or title_from_filename(filename)
    recording = Recording(
        user_id=user.id,
        title=display_title,
        # A filename-derived title is a placeholder the summary may improve; a
        # real user-provided title is authoritative and kept.
        title_auto_generated=not bool(user_title),
        type="note",
        status=RecordingStatus.PROCESSING.value,
        uploaded_at=datetime.now(timezone.utc),
        language=language,
        folder_id=folder_id,
    )
    db.add(recording)
    await db.flush()
    recording_id = str(recording.id)

    try:
        from app.tasks.media_import import import_uploaded_media_task

        import_uploaded_media_task.delay(
            user_id=str(user.id),
            recording_id=recording_id,
            staged_path=str(staged),
            filename=filename,
            content_type=content_type,
            title=clean_title(title),
            language=language,
        )
    except Exception as exc:  # noqa: BLE001 — broker down: surface, don't silently drop the file
        staged.unlink(missing_ok=True)
        recording.status = RecordingStatus.FAILED.value
        recording.failure_code = "processing_enqueue_failed"
        recording.failure_message = "Couldn't queue media processing. Please retry."
        await db.commit()
        logger.warning("media upload enqueue failed: %s", type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Couldn't queue media processing. Please retry.",
        ) from exc
    await db.commit()

    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        content={
            "kind": "recording",
            "status": "processing",
            "recording_id": recording_id,
        },
    )


def _store_item_upload(user_id: Any, ext: str, data: bytes) -> Path:
    """Persist the original upload to local disk under a UUID key (never the
    user-supplied filename — path-traversal safe). Object storage swaps in
    behind this one call later."""
    from app.config import get_settings

    base = Path(get_settings().upload_staging_dir) / "items" / str(user_id)
    base.mkdir(parents=True, exist_ok=True)
    path = base / f"{uuid4().hex}.{ext}"
    path.write_bytes(data)
    return path


@router.post("/upload", response_model=ItemResponse, status_code=status.HTTP_201_CREATED)
async def upload_item(
    user: CurrentUser,
    db: Database,
    file: UploadFile = File(...),
    folder_id: UUID | None = Form(default=None),
    title: str | None = Form(default=None),
) -> ItemResponse | JSONResponse:
    """Add any supported document as an Item, or audio/video as a Recording."""
    folder = await _require_folder(folder_id, user.id, db)
    validated_folder_id = folder.id if folder else None

    ext = resolve_document_extension(file.filename, file.content_type)
    if ext not in SUPPORTED_DOCUMENT_EXTENSIONS:
        media_ext = _media_upload_ext(file.filename, file.content_type)
        if media_ext:
            return await _handle_media_upload(
                user,
                db,
                media_ext,
                file,
                title,
                validated_folder_id,
            )
        await file.close()
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=(
                "Upload a PDF, DOCX, DOC, HTML, text, Markdown, RTF, CSV, JSON, "
                "PPTX, XLSX, audio, or video file."
            ),
        )

    from app.config import get_settings

    max_bytes = get_settings().upload_max_bytes
    buf = bytearray()
    while True:
        chunk = await file.read(_UPLOAD_CHUNK)
        if not chunk:
            break
        buf.extend(chunk)
        if len(buf) > max_bytes:
            await file.close()
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"File too large. Maximum size is {max_bytes // (1024 * 1024)}MB.",
            )
    await file.close()
    data = bytes(buf)
    if not data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Empty file.")

    try:
        body = (await extract_document_text(ext, data, usage_user_id=user.id)).strip()
    except DocumentExtractionError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=exc.message,
        ) from exc

    stored = _store_item_upload(user.id, ext, data)
    item, created = await ingest_item(
        db,
        user.id,
        source="upload",
        kind=document_kind_for_extension(ext),
        title=clean_title(title) or title_from_filename(file.filename),
        body=body,
        folder_id=validated_folder_id,
        metadata={"upload": {"ext": ext, "path": str(stored), "size": len(data)}},
        embed=True,
    )
    await db.flush()
    if created:
        await _enqueue_item_summary(db, item)
    else:
        # Dedup hit: drop the just-written original; the existing item owns its copy.
        stored.unlink(missing_ok=True)

    summary = (
        await db.execute(select(ItemSummary).where(ItemSummary.item_id == item.id))
    ).scalar_one_or_none()
    return _item_response(item, summary)


@router.get("", response_model=ItemListResponse)
async def list_items(
    user: CurrentUser,
    db: Database,
    source: str | None = Query(None, max_length=80),
    kind: str | None = Query(None, max_length=50),
    folder_id: UUID | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> ItemListResponse:
    """List the user's items newest-first (the item half of the unified feed)."""
    from sqlalchemy import func
    from sqlalchemy.orm import defer

    # The feed never renders body text or embeddings; deferring them keeps a
    # 50-row page from dragging 50 full articles + 6 KB vectors off disk. The
    # status logic only needs "is there a body", computed in SQL instead.
    has_body_expr = (func.coalesce(func.btrim(Item.body), "") != "").label("has_body")
    base = (
        select(Item, has_body_expr)
        .options(defer(Item.body), defer(Item.embedding))
        .where(Item.user_id == user.id, Item.deleted_at.is_(None))
    )
    if source:
        base = base.where(Item.source == source)
    if kind:
        base = base.where(Item.kind == kind)
    if folder_id is not None:
        folder = await _require_folder(folder_id, user.id, db)
        base = base.where(Item.folder_id == folder.id)

    result_rows = (
        await db.execute(
            base.order_by(Item.created_at.desc()).offset(offset).limit(limit)
        )
    ).all()
    rows = [row[0] for row in result_rows]
    has_body_by_id = {row[0].id: bool(row[1]) for row in result_rows}

    summarized_ids = set(
        (
            await db.execute(
                select(ItemSummary.item_id).where(
                    ItemSummary.item_id.in_([r.id for r in rows])
                )
            )
        ).scalars().all()
    ) if rows else set()

    count_q = select(func.count()).select_from(
        base.order_by(None).subquery()
    )
    total = (await db.execute(count_q)).scalar() or 0

    return ItemListResponse(
        items=[
            ItemListEntry(
                id=str(r.id),
                source=r.source,
                url=r.url,
                kind=r.kind,
                title=r.title,
                state=r.state,
                status=_derive_status(
                    r,
                    r.id in summarized_ids,
                    has_body=has_body_by_id.get(r.id, False),
                ),
                error=_item_error(r),
                folder_id=str(r.folder_id) if r.folder_id else None,
                occurred_at=r.occurred_at.isoformat() if r.occurred_at else None,
                created_at=r.created_at.isoformat(),
                has_summary=r.id in summarized_ids,
            )
            for r in rows
        ],
        total=total,
    )


@router.get("/{item_id}", response_model=ItemResponse)
async def get_item(
    item_id: UUID,
    user: CurrentUser,
    db: Database,
) -> ItemResponse:
    """Get one item with its summary + key-moments table."""
    item = (
        await db.execute(
            select(Item).where(
                Item.id == item_id,
                Item.user_id == user.id,
                Item.deleted_at.is_(None),
            )
            .options(selectinload(Item.summary_audio_artifacts))
        )
    ).scalar_one_or_none()
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Item not found"
        )
    summary = (
        await db.execute(select(ItemSummary).where(ItemSummary.item_id == item.id))
    ).scalar_one_or_none()
    return _item_response(item, summary)


@router.get("/{item_id}/summary/audio", response_model=SummaryAudioResponse)
async def get_item_summary_audio(
    item_id: UUID,
    user: CurrentUser,
    db: Database,
) -> SummaryAudioResponse:
    """Get durable summary-audio state for an item."""
    item = (
        await db.execute(
            select(Item)
            .where(Item.id == item_id, Item.user_id == user.id, Item.deleted_at.is_(None))
            .options(selectinload(Item.summary))
        )
    ).scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found")
    text_value = build_item_summary_audio_text(item.summary)
    if not text_value:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Summary not generated")
    artifact = await load_latest_summary_audio_artifact(
        db,
        source_kind=SUMMARY_AUDIO_SOURCE_ITEM,
        source_id=item.id,
        user_id=user.id,
        summary_hash=summary_audio_hash(text_value),
    )
    return serialize_summary_audio(
        source_kind=SUMMARY_AUDIO_SOURCE_ITEM,
        source_id=item.id,
        artifact=artifact,
        audio_url=f"/api/items/{item.id}/summary/audio/file",
    )


@router.post(
    "/{item_id}/summary/audio",
    response_model=SummaryAudioResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def start_item_summary_audio(
    item_id: UUID,
    user: CurrentUser,
    db: Database,
) -> SummaryAudioResponse:
    """Start or reuse durable summary-audio generation for an item."""
    try:
        artifact = await start_summary_audio_artifact(
            db,
            source_kind=SUMMARY_AUDIO_SOURCE_ITEM,
            source_id=item_id,
            user_id=user.id,
        )
    except SummaryAudioError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    await db.commit()
    if artifact.status == SummaryAudioStatus.QUEUED.value and not artifact.task_id:
        try:
            artifact.task_id = enqueue_summary_audio_generation(artifact.id)
        except Exception as exc:
            logger.exception("Failed to enqueue summary audio for item %s", item_id)
            artifact.status = SummaryAudioStatus.FAILED.value
            artifact.stage = "failed"
            artifact.progress_percent = 100
            artifact.error_code = "summary_audio_enqueue_failed"
            artifact.error_message = "Failed to start summary audio generation."
            artifact.failed_at = datetime.now(timezone.utc)
            await db.commit()
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Failed to start summary audio generation",
            ) from exc
        await db.commit()

    return serialize_summary_audio(
        source_kind=SUMMARY_AUDIO_SOURCE_ITEM,
        source_id=item_id,
        artifact=artifact,
        audio_url=f"/api/items/{item_id}/summary/audio/file",
    )


@router.get("/{item_id}/summary/audio/file")
async def get_item_summary_audio_file(
    item_id: UUID,
    request: Request,
    user: CurrentUser,
    db: Database,
) -> Response:
    """Stream authenticated generated summary audio for an item."""
    item = (
        await db.execute(
            select(Item)
            .where(Item.id == item_id, Item.user_id == user.id, Item.deleted_at.is_(None))
            .options(selectinload(Item.summary))
        )
    ).scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found")
    text_value = build_item_summary_audio_text(item.summary)
    if not text_value:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Summary not generated")
    artifact = await load_latest_summary_audio_artifact(
        db,
        source_kind=SUMMARY_AUDIO_SOURCE_ITEM,
        source_id=item.id,
        user_id=user.id,
        summary_hash=summary_audio_hash(text_value),
    )
    if artifact is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Summary audio has not been created.",
        )
    return summary_audio_file_response(artifact=artifact, request=request)


class ReprocessItemRequest(BaseModel):
    """Recover a stuck item. Provide ``body`` to paste the text we couldn't
    fetch; omit it to retry the source URL."""

    body: str | None = None


@router.post("/{item_id}/reprocess", response_model=ItemResponse)
async def reprocess_item(
    item_id: UUID,
    request: ReprocessItemRequest,
    user: CurrentUser,
    db: Database,
) -> ItemResponse:
    """Recover a needs_input / failed item: paste the text we couldn't fetch, or
    — with no body but a URL — retry the fetch. Clears the prior error, resets to
    raw, and re-runs the embed + summarize pipeline."""
    item = (
        await db.execute(
            select(Item).where(
                Item.id == item_id,
                Item.user_id == user.id,
                Item.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found")

    pasted = (request.body or "").strip()
    if pasted:
        item.body = pasted
        meta = dict(item.metadata_ or {})
        meta.pop("fetch_error", None)
        meta.pop("processing_error", None)
        item.metadata_ = meta
    elif not (item.url or "").strip() and not (item.body or "").strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Nothing to process — paste the text or add a source first.",
        )

    item.state = "raw"
    await db.flush()
    await _enqueue_item_summary(db, item)

    summary = (
        await db.execute(select(ItemSummary).where(ItemSummary.item_id == item.id))
    ).scalar_one_or_none()
    return _item_response(item, summary)


async def _load_owned_item(db: Database, item_id: UUID, user: CurrentUser) -> Item:
    item = (
        await db.execute(
            select(Item).where(
                Item.id == item_id, Item.user_id == user.id, Item.deleted_at.is_(None)
            )
        )
    ).scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found")
    return item


async def _item_with_summary(db: Database, item: Item) -> ItemResponse:
    summary = (
        await db.execute(select(ItemSummary).where(ItemSummary.item_id == item.id))
    ).scalar_one_or_none()
    return _item_response(item, summary)


class UpdateItemRequest(BaseModel):
    """Mutable item fields — today just the folder assignment."""

    folder_id: UUID | None = None


@router.patch("/{item_id}", response_model=ItemResponse)
async def update_item(
    item_id: UUID,
    request: UpdateItemRequest,
    user: CurrentUser,
    db: Database,
) -> ItemResponse:
    """Move an item into a folder (or out of one with ``folder_id: null``).

    Mirrors ``PATCH /recordings/{id}`` so the inbox can file recordings and
    materials with one gesture (drag to a sidebar folder / bulk move)."""
    item = await _load_owned_item(db, item_id, user)
    if "folder_id" in request.model_fields_set:
        folder = await _require_folder(request.folder_id, user.id, db)
        item.folder_id = folder.id if folder is not None else None
        await db.flush()
    return await _item_with_summary(db, item)


@router.post("/{item_id}/forget", response_model=ItemResponse)
async def forget_item(item_id: UUID, user: CurrentUser, db: Database) -> ItemResponse:
    """Archive an item so it stops surfacing in recall (search / feed / Ask),
    reversibly. Unlike delete (soft-delete), forget keeps the row + content and is
    restorable — the "Forget this" trust affordance, symmetric with remember()."""
    item = await _load_owned_item(db, item_id, user)
    item.state = "archived"
    await db.flush()
    return await _item_with_summary(db, item)


@router.post("/{item_id}/restore", response_model=ItemResponse)
async def restore_item(item_id: UUID, user: CurrentUser, db: Database) -> ItemResponse:
    """Un-archive a forgotten item so it surfaces in recall again."""
    item = await _load_owned_item(db, item_id, user)
    if item.state == "archived":
        item.state = "raw"
        await db.flush()
    return await _item_with_summary(db, item)


@router.delete(
    "/{item_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def delete_item(
    item_id: UUID,
    user: CurrentUser,
    db: Database,
) -> Response:
    """Soft-delete an item."""
    from datetime import datetime, timezone

    item = (
        await db.execute(
            select(Item).where(Item.id == item_id, Item.user_id == user.id)
        )
    ).scalar_one_or_none()
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Item not found"
    )
    item.deleted_at = datetime.now(timezone.utc)
    await db.flush()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
