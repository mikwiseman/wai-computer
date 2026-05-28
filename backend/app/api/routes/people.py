"""People (known speakers) CRUD + merge."""

from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select, update
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentUser, Database
from app.models import Person, PublicVoiceprint, Segment, Voiceprint

router = APIRouter(prefix="/people", tags=["people"])


class PersonResponse(BaseModel):
    """Response for a Person row, with derived voiceprint count."""

    id: str
    display_name: str
    color: str | None
    aliases: list[str] | None
    voiceprint_count: int
    created_at: datetime
    updated_at: datetime


class CreatePersonRequest(BaseModel):
    display_name: str = Field(min_length=1, max_length=200)
    color: str | None = Field(default=None, max_length=20)
    aliases: list[str] | None = None

    @field_validator("display_name")
    @classmethod
    def _strip_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("display_name cannot be empty")
        return normalized


class UpdatePersonRequest(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=200)
    color: str | None = Field(default=None, max_length=20)
    aliases: list[str] | None = None

    @field_validator("display_name")
    @classmethod
    def _strip_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("display_name cannot be empty")
        return normalized


class MergePersonRequest(BaseModel):
    into_person_id: UUID


def _serialize_person(person: Person, voiceprint_count: int = 0) -> PersonResponse:
    aliases: list[str] | None = None
    if person.aliases is not None:
        aliases = [str(item) for item in person.aliases]
    return PersonResponse(
        id=str(person.id),
        display_name=person.display_name,
        color=person.color,
        aliases=aliases,
        voiceprint_count=voiceprint_count,
        created_at=person.created_at,
        updated_at=person.updated_at,
    )


async def _voiceprint_counts(db, user_id: UUID) -> dict[UUID, int]:
    result = await db.execute(
        select(Voiceprint.person_id, func.count(Voiceprint.id))
        .where(Voiceprint.user_id == user_id)
        .group_by(Voiceprint.person_id)
    )
    return {row[0]: int(row[1]) for row in result.all()}


@router.get("", response_model=list[PersonResponse])
async def list_people(user: CurrentUser, db: Database) -> list[PersonResponse]:
    result = await db.execute(
        select(Person)
        .where(Person.user_id == user.id)
        .order_by(Person.display_name.asc())
    )
    people = result.scalars().all()
    counts = await _voiceprint_counts(db, user.id)
    return [_serialize_person(p, counts.get(p.id, 0)) for p in people]


@router.post("", response_model=PersonResponse, status_code=status.HTTP_201_CREATED)
async def create_person(
    request: CreatePersonRequest,
    user: CurrentUser,
    db: Database,
) -> PersonResponse:
    aliases_payload: Any = request.aliases if request.aliases else None
    person = Person(
        user_id=user.id,
        display_name=request.display_name,
        color=request.color,
        aliases=aliases_payload,
    )
    db.add(person)
    await db.flush()
    await db.refresh(person)
    return _serialize_person(person, voiceprint_count=0)


@router.patch("/{person_id}", response_model=PersonResponse)
async def update_person(
    person_id: UUID,
    request: UpdatePersonRequest,
    user: CurrentUser,
    db: Database,
) -> PersonResponse:
    result = await db.execute(
        select(Person).where(Person.id == person_id, Person.user_id == user.id)
    )
    person = result.scalar_one_or_none()
    if person is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Person not found")

    if request.display_name is not None:
        person.display_name = request.display_name
    if request.color is not None:
        person.color = request.color
    if request.aliases is not None:
        person.aliases = request.aliases

    await db.flush()
    await db.refresh(person)

    counts = await _voiceprint_counts(db, user.id)
    return _serialize_person(person, counts.get(person.id, 0))


@router.delete("/{person_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_person(
    person_id: UUID,
    user: CurrentUser,
    db: Database,
) -> None:
    result = await db.execute(
        select(Person).where(Person.id == person_id, Person.user_id == user.id)
    )
    person = result.scalar_one_or_none()
    if person is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Person not found")
    # Block deleting the self-Person while the user is published to the
    # directory — otherwise the next refresh would have no voiceprint to
    # publish (and the SET NULL on user.self_person_id would silently
    # leave the directory entry orphaned).
    if user.self_person_id == person.id:
        published = (
            await db.execute(
                select(PublicVoiceprint.id).where(
                    PublicVoiceprint.user_id == user.id
                )
            )
        ).scalar_one_or_none()
        if published is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "Disable voice sharing in Settings before deleting your "
                    "own speaker profile."
                ),
            )
    await db.delete(person)
    await db.flush()


@router.delete(
    "/{person_id}/voiceprints/{voiceprint_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_voiceprint(
    person_id: UUID,
    voiceprint_id: UUID,
    user: CurrentUser,
    db: Database,
) -> None:
    """Drop a single voiceprint sample without removing the Person.

    GDPR-relevant: lets a user revoke an individual biometric sample (bad
    enrollment, wrong-mic recording, no-longer-representative voice) while
    keeping the Person's display_name + aliases + segment attributions.
    """
    result = await db.execute(
        select(Voiceprint).where(
            Voiceprint.id == voiceprint_id,
            Voiceprint.person_id == person_id,
            Voiceprint.user_id == user.id,
        )
    )
    voiceprint = result.scalar_one_or_none()
    if voiceprint is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Voiceprint not found"
        )
    await db.delete(voiceprint)
    await db.flush()

    # If this was the self-Person's last voiceprint AND the user is
    # currently published, withdraw the published row so the directory
    # doesn't keep serving a vector that the user explicitly revoked.
    if user.self_person_id == person_id:
        remaining = (
            await db.execute(
                select(func.count(Voiceprint.id)).where(
                    Voiceprint.person_id == person_id,
                    Voiceprint.user_id == user.id,
                )
            )
        ).scalar_one()
        if remaining == 0:
            from app.core.voice_sharing import unpublish_voice_sharing

            await unpublish_voice_sharing(db=db, user=user)


@router.post("/{person_id}/merge", response_model=PersonResponse)
async def merge_person(
    person_id: UUID,
    request: MergePersonRequest,
    user: CurrentUser,
    db: Database,
) -> PersonResponse:
    """Move voiceprints and segments into another person, then delete source."""
    if person_id == request.into_person_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot merge a person into itself",
        )

    result = await db.execute(
        select(Person)
        .where(Person.id.in_([person_id, request.into_person_id]), Person.user_id == user.id)
        .options(selectinload(Person.voiceprints))
    )
    rows = {row.id: row for row in result.scalars().all()}
    source = rows.get(person_id)
    target = rows.get(request.into_person_id)
    if source is None or target is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Person not found"
        )

    await db.execute(
        update(Voiceprint)
        .where(Voiceprint.person_id == source.id)
        .values(person_id=target.id)
    )
    await db.execute(
        update(Segment).where(Segment.person_id == source.id).values(person_id=target.id)
    )
    await db.delete(source)
    await db.flush()

    counts = await _voiceprint_counts(db, user.id)
    return _serialize_person(target, counts.get(target.id, 0))
