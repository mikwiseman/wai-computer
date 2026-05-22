"""Promo code normalization and hashing."""

from __future__ import annotations

import hashlib
import re
import secrets

PROMO_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def normalize_promo_code(code: str) -> str:
    """Return the canonical representation used for lookup and hashing."""
    return re.sub(r"[^A-Z0-9]", "", code.upper())


def hash_promo_code(code: str) -> str:
    normalized = normalize_promo_code(code)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def generate_promo_code(*, prefix: str = "WAI", groups: int = 3, group_size: int = 4) -> str:
    parts = [prefix.upper()]
    for _ in range(groups):
        parts.append("".join(secrets.choice(PROMO_CODE_ALPHABET) for _ in range(group_size)))
    return "-".join(parts)
