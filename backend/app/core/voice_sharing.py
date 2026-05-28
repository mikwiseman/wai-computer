"""Voice-sharing directory publish / unpublish helpers.

All access to the ``public_voiceprints`` table flows through this module so
the row stays consistent with the user's profile and currently-enrolled
self-voiceprint. The matching engine in ``voice_identification.py`` reads
the table directly; only writers go through here.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.voice_embedding import MODEL_NAME
from app.models.person import Person, PublicVoiceprint, Voiceprint
from app.models.recording import Segment
from app.models.user import User

logger = logging.getLogger(__name__)


class VoiceSharingError(Exception):
    """Raised when a publish attempt fails a prerequisite check."""


@dataclass(frozen=True)
class VoiceSharingState:
    enabled: bool
    has_first_name: bool
    has_last_name: bool
    has_voiceprint: bool
    shared_name: str | None

    @property
    def can_enable(self) -> bool:
        return self.has_first_name and self.has_last_name and self.has_voiceprint


async def get_voice_sharing_state(
    *, db: AsyncSession, user: User
) -> VoiceSharingState:
    voiceprint = await _pick_publishable_voiceprint(db=db, user=user)
    published = (
        await db.execute(
            select(PublicVoiceprint).where(PublicVoiceprint.user_id == user.id)
        )
    ).scalar_one_or_none()
    shared_name = None
    if published is not None:
        shared_name = " ".join(
            part for part in (published.first_name, published.last_name) if part
        ).strip() or None
    return VoiceSharingState(
        enabled=published is not None,
        has_first_name=bool((user.first_name or "").strip()),
        has_last_name=bool((user.last_name or "").strip()),
        has_voiceprint=voiceprint is not None,
        shared_name=shared_name,
    )


async def publish_voice_sharing(
    *, db: AsyncSession, user: User
) -> VoiceSharingState:
    """Publish (or refresh) the user's directory entry.

    Raises VoiceSharingError if prerequisites are not met. Idempotent: calling
    twice updates the row to the latest voiceprint and name without creating
    duplicates.
    """
    from app.core.name_moderation import (
        NameModerationError,
        validate_combined_directory_name,
    )

    try:
        first_name, last_name = validate_combined_directory_name(
            user.first_name, user.last_name
        )
    except NameModerationError as exc:
        raise VoiceSharingError(str(exc)) from exc

    voiceprint = await _pick_publishable_voiceprint(db=db, user=user)
    if voiceprint is None:
        raise VoiceSharingError(
            "Enroll your voice before publishing to the directory."
        )

    now = datetime.now(timezone.utc)
    existing = (
        await db.execute(
            select(PublicVoiceprint).where(PublicVoiceprint.user_id == user.id)
        )
    ).scalar_one_or_none()
    if existing is None:
        db.add(
            PublicVoiceprint(
                user_id=user.id,
                voiceprint_id=voiceprint.id,
                embedding=list(voiceprint.embedding),
                embedding_model=voiceprint.model,
                first_name=first_name,
                last_name=last_name,
                published_at=now,
                updated_at=now,
            )
        )
    else:
        existing.voiceprint_id = voiceprint.id
        existing.embedding = list(voiceprint.embedding)
        existing.embedding_model = voiceprint.model
        existing.first_name = first_name
        existing.last_name = last_name
        existing.updated_at = now
    await db.flush()
    return await get_voice_sharing_state(db=db, user=user)


async def unpublish_voice_sharing(
    *, db: AsyncSession, user: User
) -> VoiceSharingState:
    """Remove the user's directory entry and propagate the withdrawal.

    GDPR right-to-erasure requires we don't just delete the publish row; we
    also stop existing receivers from displaying our name on past or future
    matches. Concretely:
      - Hard-delete the public_voiceprints row.
      - For every receiver Person whose ``directory_user_id`` points at this
        user, sever the link (set directory_user_id NULL) and rename the
        Person to a neutral fallback so receivers see something stable but
        not our published identity.
      - Clear ``person_id`` on Segments that were AUTO-assigned via the
        directory (auto_assigned=True) and whose Person was directory-linked;
        manual assignments by the receiver are preserved.

    Idempotent.
    """
    await db.execute(
        delete(PublicVoiceprint).where(PublicVoiceprint.user_id == user.id)
    )

    # Snapshot receiver Person rows we need to unlink, so we can clear the
    # downstream Segment attributions before the FK is severed.
    rows = await db.execute(
        select(Person.id).where(Person.directory_user_id == user.id)
    )
    receiver_person_ids = [row[0] for row in rows.all()]

    if receiver_person_ids:
        await db.execute(
            update(Segment)
            .where(
                Segment.person_id.in_(receiver_person_ids),
                Segment.auto_assigned.is_(True),
            )
            .values(person_id=None, auto_assigned=False, match_confidence=None)
        )
        await db.execute(
            update(Person)
            .where(Person.id.in_(receiver_person_ids))
            .values(
                directory_user_id=None,
                display_name="Removed from WaiComputer directory",
            )
        )

    await db.flush()
    return await get_voice_sharing_state(db=db, user=user)


async def refresh_published_voiceprint_if_any(
    *, db: AsyncSession, user: User
) -> None:
    """Best-effort: if user is currently published, refresh the snapshot.

    Called after a re-enrollment so the directory always points at the user's
    most recent voiceprint without requiring them to flip the toggle again.
    Silently no-ops if not currently published.
    """
    published = (
        await db.execute(
            select(PublicVoiceprint).where(PublicVoiceprint.user_id == user.id)
        )
    ).scalar_one_or_none()
    if published is None:
        return
    try:
        await publish_voice_sharing(db=db, user=user)
    except VoiceSharingError as exc:
        logger.warning(
            "could not refresh published voiceprint for user_id=%s reason=%s",
            user.id,
            exc,
        )


async def _pick_publishable_voiceprint(
    *, db: AsyncSession, user: User
) -> Voiceprint | None:
    """Pick the user's canonical self-voiceprint to publish.

    Only returns a Voiceprint attached to ``user.self_person_id``. We
    deliberately do NOT fall back to "latest voiceprint of any Person" —
    that fallback could publish a spouse / colleague / contact's voice
    under the user's name if they ever delete their own self-Person.
    Returning None forces the caller to surface a clear "re-enroll your
    voice" error path.
    """
    if user.self_person_id is None:
        return None
    result = await db.execute(
        select(Voiceprint)
        .where(
            Voiceprint.user_id == user.id,
            Voiceprint.person_id == user.self_person_id,
            Voiceprint.model == MODEL_NAME,
        )
        .order_by(Voiceprint.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()
