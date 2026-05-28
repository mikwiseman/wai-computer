"""Voice enrollment endpoint for cross-recording speaker identification."""

import logging
import uuid
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import func, select

from app.api.deps import CurrentUser, Database
from app.api.routes.people import PersonResponse, _serialize_person, _voiceprint_counts
from app.config import get_settings
from app.core.voice_identification import store_voiceprint_from_path
from app.core.voice_sharing import refresh_published_voiceprint_if_any
from app.models import Person

logger = logging.getLogger(__name__)
app_settings = get_settings()

router = APIRouter(prefix="/voice-enrollment", tags=["voice-enrollment"])

MIN_DURATION_S = 5.0
MAX_DURATION_S = 60.0
MAX_BYTES = 50 * 1024 * 1024  # 50 MB safety cap on enrollment uploads


class VoiceEnrollmentResponse(BaseModel):
    """Returned after a successful voice enrollment."""

    person: PersonResponse
    voiceprint_id: str
    duration_s: float


@router.post("", response_model=VoiceEnrollmentResponse)
async def enroll_voice(
    user: CurrentUser,
    db: Database,
    audio: UploadFile = File(...),
    display_name: str | None = Form(default=None, max_length=200),
    person_id: UUID | None = Form(default=None),
) -> VoiceEnrollmentResponse:
    """Enroll a voice sample for the calling user.

    - If ``person_id`` is supplied, attach a new voiceprint to that existing Person.
    - Otherwise look up an existing Person owned by this user with the same
      ``display_name`` (case-insensitive); reuse it if found.
    - Otherwise create a new Person with that ``display_name`` (default "You")
      and attach the first voiceprint.

    Audio is staged on disk only for the duration of the request; the ECAPA
    embedding is computed and persisted, then the staged file is deleted.
    """
    staging_dir = Path(app_settings.upload_staging_dir) / "voice-enrollment"
    staging_dir.mkdir(parents=True, exist_ok=True)
    staged_path = staging_dir / f"{user.id}-{uuid.uuid4().hex}{_safe_ext(audio.filename)}"

    total_bytes = 0
    try:
        with staged_path.open("wb") as staged_file:
            while True:
                chunk = await audio.read(1024 * 1024)
                if not chunk:
                    break
                total_bytes += len(chunk)
                if total_bytes > MAX_BYTES:
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail=f"Voice sample exceeds {MAX_BYTES // (1024 * 1024)} MB.",
                    )
                staged_file.write(chunk)

        duration_s = _measure_duration_seconds(staged_path)
        if duration_s < MIN_DURATION_S:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"Voice sample is too short ({duration_s:.1f}s). "
                    f"Record at least {int(MIN_DURATION_S)} seconds."
                ),
            )
        if duration_s > MAX_DURATION_S:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"Voice sample is too long ({duration_s:.1f}s). "
                    f"Keep it under {int(MAX_DURATION_S)} seconds."
                ),
            )

        person = await _resolve_person(
            db=db, user_id=user.id, person_id=person_id, display_name=display_name
        )

        voiceprint_id = await store_voiceprint_from_path(
            db=db,
            user_id=user.id,
            person_id=person.id,
            audio_path=staged_path,
            start_ms=0,
            end_ms=int(duration_s * 1000),
            source_recording_id=None,
        )

        # First enrollment seeds the canonical self-Person pointer. We never
        # overwrite an existing pointer here — the user can rebind via the
        # dedicated identity endpoint if they enrolled the wrong Person first.
        if user.self_person_id is None:
            user.self_person_id = person.id
            await db.flush()

        # If the user already opted into the directory, this enrollment may be
        # a re-enrollment that should replace the published voiceprint. No-op
        # if not currently published.
        await refresh_published_voiceprint_if_any(db=db, user=user)

        counts = await _voiceprint_counts(db, user.id)
        return VoiceEnrollmentResponse(
            person=_serialize_person(person, counts.get(person.id, 0)),
            voiceprint_id=str(voiceprint_id),
            duration_s=round(duration_s, 2),
        )
    finally:
        try:
            staged_path.unlink(missing_ok=True)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to delete enrolled voice sample %s: %s", staged_path, exc)


def _safe_ext(filename: str | None) -> str:
    if not filename or "." not in filename:
        return ".wav"
    ext = "." + filename.rsplit(".", 1)[-1].lower()
    if not ext.isascii() or len(ext) > 6:
        return ".wav"
    return ext


def _measure_duration_seconds(path: Path) -> float:
    """Return the audio duration in seconds. Raises 422 if the file cannot be decoded."""
    from pydub import AudioSegment

    try:
        segment = AudioSegment.from_file(str(path))
    except Exception as exc:  # noqa: BLE001
        logger.info("Voice enrollment decode failed for %s: %s", path.name, exc)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Could not decode the audio file. Try WAV, MP3, M4A, or OGG.",
        ) from exc
    return len(segment) / 1000.0


async def _resolve_person(
    *,
    db: Database,
    user_id: UUID,
    person_id: UUID | None,
    display_name: str | None,
) -> Person:
    if person_id is not None:
        result = await db.execute(
            select(Person).where(Person.id == person_id, Person.user_id == user_id)
        )
        person = result.scalar_one_or_none()
        if person is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Person not found"
            )
        return person

    normalized = (display_name or "You").strip() or "You"
    if len(normalized) > 200:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="display_name must be 200 characters or fewer",
        )

    existing = await db.execute(
        select(Person).where(
            Person.user_id == user_id,
            func.lower(Person.display_name) == normalized.lower(),
        )
    )
    people = existing.scalars().all()
    if len(people) == 1:
        return people[0]
    if len(people) > 1:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Multiple people match display_name; provide person_id",
        )

    person = Person(user_id=user_id, display_name=normalized)
    db.add(person)
    await db.flush()
    await db.refresh(person)
    return person
