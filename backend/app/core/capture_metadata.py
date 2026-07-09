"""Client capture sidecar: parsing and owner-speaker attribution.

Native clients record the microphone and system audio as separate streams
before mixing. The mic stream is physical ground truth for "when did the
device owner speak", so the client ships a compact sidecar with the upload:
merged ``[start_ms, end_ms]`` intervals of local (mic) speech. After
diarization, the cluster that dominates those intervals IS the owner — no
voiceprint guesswork needed for "Me".

The sidecar is an enhancement to speaker attribution, never a gate on
transcription: a malformed sidecar is surfaced (log + Sentry anomaly) and
attribution falls back to voiceprint matching alone.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.person import Person
from app.models.user import User

MAX_CAPTURE_METADATA_BYTES = 64 * 1024
CAPTURE_MODES = {"mic_only", "dual_mono_mix", "dual_two_channel"}
CAPTURE_METADATA_VERSION = 1

# The owner cluster must both sit inside local-speech time and explain most of
# it. The first guard stops "the person who talks the most" from stealing the
# label; the second stops a tiny incidental cluster from claiming ownership.
OWNER_MIN_CLUSTER_OVERLAP = 0.6
OWNER_MIN_LOCAL_COVERAGE = 0.5


@dataclass(frozen=True)
class CaptureMetadata:
    """Validated capture sidecar uploaded alongside a recording."""

    version: int
    capture: str
    local_speech_ms: list[tuple[int, int]]
    aec: bool = False

    def as_dict(self) -> dict:
        return {
            "version": self.version,
            "capture": self.capture,
            "local_speech_ms": [list(pair) for pair in self.local_speech_ms],
            "aec": self.aec,
        }


class CaptureMetadataError(ValueError):
    """Raised when a capture sidecar fails validation."""


def _validated_intervals(raw: object) -> list[tuple[int, int]]:
    if not isinstance(raw, list):
        raise CaptureMetadataError("local_speech_ms must be a list")
    intervals: list[tuple[int, int]] = []
    previous_end = -1
    for entry in raw:
        if (
            not isinstance(entry, (list, tuple))
            or len(entry) != 2
            or isinstance(entry[0], bool)
            or isinstance(entry[1], bool)
            or not isinstance(entry[0], int)
            or not isinstance(entry[1], int)
        ):
            raise CaptureMetadataError("local_speech_ms entries must be [start_ms, end_ms]")
        start, end = int(entry[0]), int(entry[1])
        if start < 0 or end <= start:
            raise CaptureMetadataError("local_speech_ms entries must satisfy 0 <= start < end")
        if start <= previous_end:
            raise CaptureMetadataError("local_speech_ms entries must be sorted and disjoint")
        previous_end = end
        intervals.append((start, end))
    return intervals


def parse_capture_metadata(raw: str) -> CaptureMetadata:
    """Parse and validate the sidecar JSON. Raises CaptureMetadataError."""
    if len(raw.encode("utf-8", errors="ignore")) > MAX_CAPTURE_METADATA_BYTES:
        raise CaptureMetadataError("capture metadata too large")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise CaptureMetadataError(f"capture metadata is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise CaptureMetadataError("capture metadata must be a JSON object")
    version = payload.get("version")
    if version != CAPTURE_METADATA_VERSION:
        raise CaptureMetadataError(f"unsupported capture metadata version: {version!r}")
    capture = payload.get("capture")
    if capture not in CAPTURE_MODES:
        raise CaptureMetadataError(f"unsupported capture mode: {capture!r}")
    aec = payload.get("aec", False)
    if not isinstance(aec, bool):
        raise CaptureMetadataError("aec must be a boolean")
    return CaptureMetadata(
        version=version,
        capture=capture,
        local_speech_ms=_validated_intervals(payload.get("local_speech_ms")),
        aec=aec,
    )


def capture_metadata_from_stored(payload: object) -> CaptureMetadata | None:
    """Rehydrate a stored (already-validated) sidecar; None when absent/invalid."""
    if not isinstance(payload, dict):
        return None
    try:
        return parse_capture_metadata(json.dumps(payload))
    except CaptureMetadataError:
        return None


class _TimedSegment:
    """Protocol-ish view of persisted segments used by owner attribution."""

    speaker: str | None
    start_ms: int | None
    end_ms: int | None


def _overlap_ms(
    start_ms: int, end_ms: int, intervals: list[tuple[int, int]]
) -> int:
    total = 0
    for interval_start, interval_end in intervals:
        if interval_end <= start_ms:
            continue
        if interval_start >= end_ms:
            break
        total += min(end_ms, interval_end) - max(start_ms, interval_start)
    return total


def resolve_owner_raw_label(
    segments: list,
    local_speech_ms: list[tuple[int, int]],
    *,
    min_cluster_overlap: float = OWNER_MIN_CLUSTER_OVERLAP,
    min_local_coverage: float = OWNER_MIN_LOCAL_COVERAGE,
) -> str | None:
    """Return the diarization label that physically matches local-mic speech.

    ``segments`` need ``speaker`` (raw label), ``start_ms`` and ``end_ms``.
    Returns None when no cluster passes both dominance thresholds — an
    ambiguous mapping must not guess.
    """
    if not local_speech_ms:
        return None
    local_total_ms = sum(end - start for start, end in local_speech_ms)
    if local_total_ms <= 0:
        return None

    label_total: dict[str, int] = {}
    label_overlap: dict[str, int] = {}
    for segment in segments:
        label = getattr(segment, "speaker", None)
        start_ms = getattr(segment, "start_ms", None)
        end_ms = getattr(segment, "end_ms", None)
        if not label or start_ms is None or end_ms is None or end_ms <= start_ms:
            continue
        label_total[label] = label_total.get(label, 0) + (end_ms - start_ms)
        label_overlap[label] = label_overlap.get(label, 0) + _overlap_ms(
            start_ms, end_ms, local_speech_ms
        )

    best_label: str | None = None
    best_overlap = 0
    for label, overlap in label_overlap.items():
        if overlap > best_overlap:
            best_label = label
            best_overlap = overlap

    if best_label is None or best_overlap <= 0:
        return None
    cluster_overlap = best_overlap / label_total[best_label]
    local_coverage = best_overlap / local_total_ms
    if cluster_overlap < min_cluster_overlap or local_coverage < min_local_coverage:
        return None
    return best_label


async def ensure_self_person(db: AsyncSession, *, user: User) -> UUID:
    """Return the user's self Person id, creating the Person on first use.

    Mirrors the voice-enrollment convention: an existing ``self_person_id`` is
    never rebound here; first attribution seeds it.
    """
    if user.self_person_id is not None:
        return user.self_person_id
    display_name = " ".join(
        part for part in [(user.first_name or "").strip(), (user.last_name or "").strip()] if part
    ) or "You"
    result = await db.execute(
        select(Person).where(
            Person.user_id == user.id, Person.display_name == display_name
        )
    )
    person = result.scalars().first()
    if person is None:
        person = Person(user_id=user.id, display_name=display_name)
        db.add(person)
        await db.flush()
    user.self_person_id = person.id
    await db.flush()
    return person.id
