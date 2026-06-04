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

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import CurrentUser, Database
from app.core.document_extract import (
    SUPPORTED_DOCUMENT_EXTENSIONS,
    DocumentExtractionError,
    document_kind_for_extension,
    extract_document_text,
    resolve_document_extension,
)
from app.core.item_ingest import ingest_item
from app.core.item_titles import clean_title, title_from_filename
from app.models.item import Item, ItemSummary
from app.models.recording import Folder, Recording, RecordingStatus

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


def _derive_status(item: Item, has_summary: bool) -> str:
    """Derive a client-facing processing status from the item's state + data.

    Honest statuses only: ``needs_input`` (a recoverable fetch error the user
    can resolve), ``failed`` (processing could not start), ``ready`` (summary
    present), ``fetching`` (URL awaiting its background fetch), ``summarizing``
    (body present, summary pending).
    """
    if item.state == "needs_input":
        return "needs_input"
    meta = item.metadata_ or {}
    if item.state == "failed" or meta.get("processing_error"):
        return "failed"
    if has_summary:
        return "ready"
    if not (item.body or "").strip() and (item.url or "").strip():
        return "fetching"
    return "summarizing"


def _item_response(item: Item, summary: ItemSummary | None) -> ItemResponse:
    return ItemResponse(
        id=str(item.id),
        source=item.source,
        source_ref=item.source_ref,
        url=item.url,
        kind=item.kind,
        title=item.title,
        body=item.body,
        occurred_at=item.occurred_at.isoformat() if item.occurred_at else None,
        state=item.state,
        status=_derive_status(item, summary is not None),
        error=_item_error(item),
        folder_id=str(item.folder_id) if item.folder_id else None,
        created_at=item.created_at.isoformat(),
        summary=_summary_response(summary),
    )


async def _enqueue_item_summary(db: Database, item: Item) -> None:
    """Enqueue background summarization. On broker failure, mark the item failed
    with a visible error (no silent swallow) so the client can see + retry."""
    try:
        from app.tasks.item_summary_generation import generate_item_summary_task

        generate_item_summary_task.delay(item_id=str(item.id))
    except Exception as exc:  # noqa: BLE001 — broker down: fail loudly, never pretend success
        logger.warning("item enqueue failed item=%s: %s", item.id, exc)
        meta = dict(item.metadata_ or {})
        meta["processing_error"] = {
            "code": "enqueue_failed",
            "message": "Couldn't start processing. Retry shortly.",
        }
        item.metadata_ = meta
        item.state = "failed"
        await db.flush()


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

    display_title = clean_title(title) or title_from_filename(filename)
    recording = Recording(
        user_id=user.id,
        title=display_title,
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
    base = select(Item).where(Item.user_id == user.id, Item.deleted_at.is_(None))
    if source:
        base = base.where(Item.source == source)
    if kind:
        base = base.where(Item.kind == kind)
    if folder_id is not None:
        folder = await _require_folder(folder_id, user.id, db)
        base = base.where(Item.folder_id == folder.id)

    rows = (
        await db.execute(
            base.order_by(Item.created_at.desc()).offset(offset).limit(limit)
        )
    ).scalars().all()

    summarized_ids = set(
        (
            await db.execute(
                select(ItemSummary.item_id).where(
                    ItemSummary.item_id.in_([r.id for r in rows])
                )
            )
        ).scalars().all()
    ) if rows else set()

    from sqlalchemy import func

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
                status=_derive_status(r, r.id in summarized_ids),
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
