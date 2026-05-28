"""Tests for voice directory display-name moderation."""

from __future__ import annotations

import pytest

from app.core import name_moderation as moderation
from app.core.name_moderation import (
    NameModerationError,
    normalise_name,
    validate_combined_directory_name,
    validate_directory_name_part,
)


def test_normalise_name_handles_none_and_whitespace() -> None:
    assert normalise_name(None) is None
    assert normalise_name("  Anna  ") == "Anna"
    assert normalise_name("   ") is None


def test_validate_directory_name_part_accepts_simple_human_names() -> None:
    assert validate_directory_name_part("Anne-Marie O'Neil", field="first_name") == (
        "Anne-Marie O'Neil"
    )


@pytest.mark.parametrize(
    ("value", "message"),
    [
        ("", "cannot be empty"),
        ("x" * 121, "120 characters"),
        ("John\u200d", "non-printable"),
        ("John2", "can only contain letters"),
        ("Support", "reserved word"),
    ],
)
def test_validate_directory_name_part_rejects_directory_attack_surface(
    value: str,
    message: str,
) -> None:
    with pytest.raises(NameModerationError, match=message):
        validate_directory_name_part(value, field="first_name")


def test_validate_combined_directory_name_requires_two_non_reserved_parts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(NameModerationError, match="Both first and last"):
        validate_combined_directory_name("Anna", None)

    monkeypatch.setattr(moderation, "_RESERVED_TOKENS", {"wai computer"})
    with pytest.raises(NameModerationError, match="combined name is reserved"):
        validate_combined_directory_name("Wai", "Computer")

    assert validate_combined_directory_name(" Anna ", " Wise ") == ("Anna", "Wise")
