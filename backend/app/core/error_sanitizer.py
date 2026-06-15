"""User-facing error sanitization.

The ``failure_message`` column on ``recordings`` is rendered directly in the
client UI (web library, macOS app, iOS app, share page). Some failure paths
pre-2026-05-26 stored raw exception strings — those strings can include
absolute filesystem paths, ``[Errno …]`` codes, Python tracebacks, or
``<class '…'>`` repr fragments. Leaking those to the UI is both embarrassing
and a small information-disclosure risk.

This module normalizes any string before it's written into
``recording.failure_message`` (or any other user-visible failure field):

* Messages that look like raw OS / interpreter output collapse to a single
  generic line.
* Domain failure messages we already control ("Audio too short",
  "Transcription quota exceeded", localized "Мы не обнаружили разборчивой
  речи…", etc.) pass through untouched.
* Empty strings collapse to ``None`` so the UI shows nothing instead of a
  misleading message.
"""

from __future__ import annotations

import re

GENERIC_FAILURE_MESSAGE = (
    "We couldn't process this recording. Please try again or contact support."
)

# Patterns that strongly suggest a leaked OS / interpreter string. Any match
# triggers a full replacement with the generic message — we never try to
# "redact" the leaking pattern in place, because partial scrubs still expose
# request flow.
_LEAK_PATTERNS: tuple[re.Pattern[str], ...] = (
    # Absolute POSIX paths under common system / app dirs.
    re.compile(r"(?:^|[\s'\"`(\[])(?:/var|/tmp|/opt|/etc|/root|/home|/Users|/private)/"),
    # Drive-letter paths from developer laptops.
    re.compile(r"[A-Za-z]:\\\\"),
    re.compile(r"[A-Za-z]:/"),
    # Python traceback signatures.
    re.compile(r"Traceback \(most recent call last\)"),
    re.compile(r'\n  File "[^"]+", line \d+'),
    # POSIX errno repr ("[Errno 13] Permission denied: …").
    re.compile(r"\[Errno \d+\]"),
    # Python type repr ("<class 'sqlalchemy.exc.IntegrityError'>").
    re.compile(r"<class '[^']+'>"),
    # Generic ``module.Class:`` exception preamble at the start of a string.
    re.compile(r"^[A-Za-z_][\w.]*Error: "),
    re.compile(r"^[A-Za-z_][\w.]*Exception: "),
)

_MAX_LENGTH = 500


def sanitize_failure_message(message: str | None) -> str | None:
    """Return a user-friendly failure message stripped of paths / tracebacks.

    Returns ``None`` for empty / whitespace input so callers can store ``NULL``
    instead of an empty string.
    """
    if message is None:
        return None
    stripped = message.strip()
    if not stripped:
        return None

    for pattern in _LEAK_PATTERNS:
        if pattern.search(stripped):
            return GENERIC_FAILURE_MESSAGE

    if len(stripped) > _MAX_LENGTH:
        return stripped[:_MAX_LENGTH]
    return stripped
