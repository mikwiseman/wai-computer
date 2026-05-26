"""Speaker label helpers.

The transcription providers emit diarization labels like ``speaker_0`` /
``speaker_1`` / ``speaker_?``. Those raw labels are fine internally but leak
DB-side identifiers when surfaced in the UI — especially on the public
``/share/<token>`` page where strangers see them.

When a segment has no resolved :class:`app.models.person.Person` we fall back
to a position-derived label here. The web/native clients localize further.
"""

from __future__ import annotations

import re

_RAW_SPEAKER_LABEL_PATTERN = re.compile(r"^speaker[_\s-]?(\d+)$", re.IGNORECASE)


def fallback_speaker_display_name(speaker: str | None) -> str | None:
    """Convert raw diarization labels (``speaker_0``) into ``Speaker 1`` etc.

    Returns ``None`` for unknown or missing labels (including ``speaker_?``)
    so the client can render its own placeholder.
    """
    if not speaker:
        return None
    match = _RAW_SPEAKER_LABEL_PATTERN.match(speaker.strip())
    if match is None:
        return None
    try:
        index = int(match.group(1))
    except ValueError:
        return None
    return f"Speaker {index + 1}"
