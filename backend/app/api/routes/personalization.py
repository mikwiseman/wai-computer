"""User personalization terminology routes."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.deps import CurrentUser, Database
from app.core.personalization import (
    IMPORT_SOURCE_TYPES,
    MAX_IMPORT_TEXT_CHARS,
    TERM_STATUS_VALUES,
    clean_term,
    normalize_term,
    process_personalization_import,
)
from app.models.personalization import PersonalizationImportJob, PersonalizationTerm

router = APIRouter(prefix="/personalization", tags=["personalization"])

_SUPPORTED_IMPORT_EXTENSIONS = {".txt", ".md", ".csv"}


class PersonalizationTermResponse(BaseModel):
    id: str
    user_id: str
    import_job_id: str | None
    term: str
    normalized_term: str
    replacement: str | None
    notes: str | None
    source: str
    status: str
    frequency: int
    created_at: datetime
    updated_at: datetime


class PersonalizationImportJobResponse(BaseModel):
    id: str
    user_id: str
    source_type: str
    source_name: str | None
    status: str
    candidate_count: int
    error_code: str | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime


class CreatePersonalizationTermRequest(BaseModel):
    term: str = Field(min_length=1, max_length=200)
    replacement: str | None = Field(default=None, max_length=200)
    notes: str | None = Field(default=None, max_length=4000)

    @field_validator("term", "replacement", mode="before")
    @classmethod
    def normalize_short_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = clean_term(value)
        return cleaned or None

    @field_validator("notes", mode="before")
    @classmethod
    def normalize_notes(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class UpdatePersonalizationTermRequest(BaseModel):
    status: Literal["active", "candidate", "rejected"] | None = None
    replacement: str | None = Field(default=None, max_length=200)
    notes: str | None = Field(default=None, max_length=4000)

    @field_validator("replacement", mode="before")
    @classmethod
    def normalize_replacement(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = clean_term(value)
        return cleaned or None

    @field_validator("notes", mode="before")
    @classmethod
    def normalize_notes(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


def _serialize_term(term: PersonalizationTerm) -> PersonalizationTermResponse:
    return PersonalizationTermResponse(
        id=str(term.id),
        user_id=str(term.user_id),
        import_job_id=str(term.import_job_id) if term.import_job_id else None,
        term=term.term,
        normalized_term=term.normalized_term,
        replacement=term.replacement,
        notes=term.notes,
        source=term.source,
        status=term.status,
        frequency=term.frequency,
        created_at=term.created_at,
        updated_at=term.updated_at,
    )


def _serialize_job(job: PersonalizationImportJob) -> PersonalizationImportJobResponse:
    return PersonalizationImportJobResponse(
        id=str(job.id),
        user_id=str(job.user_id),
        source_type=job.source_type,
        source_name=job.source_name,
        status=job.status,
        candidate_count=job.candidate_count,
        error_code=job.error_code,
        error_message=job.error_message,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


async def _load_term(term_id: UUID, user_id: UUID, db: Database) -> PersonalizationTerm:
    result = await db.execute(
        select(PersonalizationTerm).where(
            PersonalizationTerm.id == term_id,
            PersonalizationTerm.user_id == user_id,
        )
    )
    term = result.scalar_one_or_none()
    if term is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Term not found")
    return term


@router.get("/terms", response_model=list[PersonalizationTermResponse])
async def list_personalization_terms(
    user: CurrentUser,
    db: Database,
    status_filter: Literal["active", "candidate", "rejected", "all"] = Query(
        "active",
        alias="status",
    ),
) -> list[PersonalizationTermResponse]:
    query = select(PersonalizationTerm).where(PersonalizationTerm.user_id == user.id)
    if status_filter != "all":
        query = query.where(PersonalizationTerm.status == status_filter)
    query = query.order_by(PersonalizationTerm.status, PersonalizationTerm.term)
    result = await db.execute(query)
    return [_serialize_term(term) for term in result.scalars().all()]


@router.post(
    "/terms",
    response_model=PersonalizationTermResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_personalization_term(
    request: CreatePersonalizationTermRequest,
    user: CurrentUser,
    db: Database,
) -> PersonalizationTermResponse:
    normalized = normalize_term(request.term)
    if not normalized:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Term is empty",
        )
    term = PersonalizationTerm(
        user_id=user.id,
        term=request.term,
        normalized_term=normalized,
        replacement=request.replacement,
        notes=request.notes,
        source="manual",
        status="active",
        frequency=1,
    )
    db.add(term)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Term already exists",
        ) from exc
    await db.refresh(term)
    return _serialize_term(term)


@router.patch("/terms/{term_id}", response_model=PersonalizationTermResponse)
async def update_personalization_term(
    term_id: UUID,
    request: UpdatePersonalizationTermRequest,
    user: CurrentUser,
    db: Database,
) -> PersonalizationTermResponse:
    term = await _load_term(term_id, user.id, db)
    if request.status is not None:
        if request.status not in TERM_STATUS_VALUES:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Invalid status",
            )
        term.status = request.status
    if "replacement" in request.model_fields_set:
        term.replacement = request.replacement
    if "notes" in request.model_fields_set:
        term.notes = request.notes
    await db.commit()
    await db.refresh(term)
    return _serialize_term(term)


@router.delete(
    "/terms/{term_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
async def delete_personalization_term(
    term_id: UUID,
    user: CurrentUser,
    db: Database,
) -> None:
    term = await _load_term(term_id, user.id, db)
    await db.delete(term)
    await db.commit()


@router.post(
    "/imports",
    response_model=PersonalizationImportJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_personalization_import(
    user: CurrentUser,
    db: Database,
    source_type: str = Form(...),
    text: str | None = Form(None),
    file: UploadFile | None = File(None),
) -> PersonalizationImportJobResponse:
    normalized_source_type = source_type.strip().lower()
    if normalized_source_type not in IMPORT_SOURCE_TYPES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid source type",
        )

    source_name: str | None = None
    if normalized_source_type == "text":
        source_text = (text or "").strip()
        source_name = "paste"
    else:
        if file is None or not file.filename:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="File is required",
            )
        suffix = "." + file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
        if suffix not in _SUPPORTED_IMPORT_EXTENSIONS:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail="Unsupported terminology import file type",
            )
        source_name = file.filename[:255]
        source_text = (await file.read()).decode("utf-8")

    if not source_text:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Import text is empty",
        )
    if len(source_text) > MAX_IMPORT_TEXT_CHARS:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Import text is too large",
        )

    job = PersonalizationImportJob(
        user_id=user.id,
        source_type=normalized_source_type,
        source_name=source_name,
        status="queued",
        source_text=source_text,
    )
    db.add(job)
    await db.flush()
    await process_personalization_import(db, job=job)
    await db.commit()
    await db.refresh(job)
    return _serialize_job(job)
