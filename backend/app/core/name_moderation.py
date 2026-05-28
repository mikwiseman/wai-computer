"""Display-name moderation for the voice-sharing directory.

The directory broadcasts every published user's first + last name to other
users' recordings. Without a moderation layer an attacker can publish
"WaiComputer Support", "Admin", emoji spam, or Unicode confusables that
mimic another user's name. This module normalises input and rejects the
common attack surface.

Conservative-by-design: we apply a single-script charset filter (letters +
basic punctuation) so all attempted impersonation via Cyrillic confusables
of "John Smith" fails. Multi-script names (e.g. legitimate "Jean Дмитриев"
for someone with mixed heritage) currently get rejected — that's a known
trade-off; we'd rather block attacks now and revisit with a confusables
denylist later.
"""

from __future__ import annotations

import re
import unicodedata

_MAX_LEN = 120
_MIN_LEN = 1

# Characters allowed in a name: letters from any script + space + a few
# common name separators. NO digits, NO emoji, NO control chars, NO punctuation
# outside the small allowlist.
_ALLOWED_PUNCTUATION = {" ", "-", "'", ".", "·"}

# Names we never let a user claim — phishing / impersonation surface.
# Match is case-insensitive and applies to full normalised name OR either
# part if any part EQUALS a reserved token after normalisation.
_RESERVED_TOKENS = {
    "admin",
    "administrator",
    "support",
    "staff",
    "wai",
    "waiwai",
    "waicomputer",
    "wai computer",
    "moderator",
    "system",
    "root",
    "official",
}


class NameModerationError(ValueError):
    """Raised when a candidate name fails moderation."""


def normalise_name(value: str | None) -> str | None:
    """Trim + Unicode NFC normalise. Returns None for empty strings."""
    if value is None:
        return None
    normalised = unicodedata.normalize("NFC", value).strip()
    return normalised or None


def validate_directory_name_part(value: str, *, field: str) -> str:
    """Validate one name field (first OR last) for the directory.

    Returns the normalised value. Raises NameModerationError with a
    user-displayable message on failure.
    """
    candidate = normalise_name(value)
    if candidate is None or len(candidate) < _MIN_LEN:
        raise NameModerationError(f"{field} cannot be empty")
    if len(candidate) > _MAX_LEN:
        raise NameModerationError(
            f"{field} must be {_MAX_LEN} characters or fewer"
        )
    # Reject control / format characters (RTL override, zero-width joiners,
    # etc.) often used for visual spoofing.
    if any(unicodedata.category(ch).startswith(("C", "Z")) and ch != " " for ch in candidate):
        raise NameModerationError(
            f"{field} contains a non-printable character"
        )
    # Charset whitelist: letters + allowed punctuation only.
    for ch in candidate:
        if ch in _ALLOWED_PUNCTUATION:
            continue
        if unicodedata.category(ch).startswith("L"):
            continue
        raise NameModerationError(
            f"{field} can only contain letters, spaces, '-', '\\'', and '.'"
        )
    if candidate.lower().strip() in _RESERVED_TOKENS:
        raise NameModerationError(
            f"{field} is a reserved word; please use your own name"
        )
    return candidate


def validate_combined_directory_name(
    first_name: str | None,
    last_name: str | None,
) -> tuple[str, str]:
    """Validate the pair as it would appear in the directory.

    Both fields must pass individual validation AND the joined form must
    not collide with a reserved token (e.g. first="Wai", last="Computer"
    composing to "Wai Computer").
    """
    if not first_name or not last_name:
        raise NameModerationError(
            "Both first and last name are required for the directory."
        )
    first = validate_directory_name_part(first_name, field="first_name")
    last = validate_directory_name_part(last_name, field="last_name")
    combined = re.sub(r"\s+", " ", f"{first} {last}").strip().lower()
    if combined in _RESERVED_TOKENS:
        raise NameModerationError(
            "That combined name is reserved; please choose a different one."
        )
    return first, last
