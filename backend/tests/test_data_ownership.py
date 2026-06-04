"""Data ownership and self-hosting contract tests."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from app.core.data_ownership import (
    ARTIFACT_OWNERSHIP,
    DATA_OWNERSHIP,
    OWNERSHIP_CLASSIFICATIONS,
    ownership_map_response,
    table_ownership_by_name,
)
from app.models import Base


def _tablename_literals() -> set[str]:
    model_root = Path(__file__).resolve().parents[1] / "app" / "models"
    names: set[str] = set()
    for path in model_root.glob("*.py"):
        if path.name in {"__init__.py", "base.py"}:
            continue
        module = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(module):
            if not isinstance(node, ast.Assign):
                continue
            if not any(
                isinstance(target, ast.Name) and target.id == "__tablename__"
                for target in node.targets
            ):
                continue
            if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                names.add(node.value.value)
    return names


def test_every_model_table_has_data_ownership_classification() -> None:
    classified = set(table_ownership_by_name())
    metadata_tables = set(Base.metadata.tables)
    source_tables = _tablename_literals()

    missing = sorted((metadata_tables | source_tables) - classified)
    assert missing == []


def test_ownership_classifications_are_known_and_have_reasons() -> None:
    for entry in [*DATA_OWNERSHIP, *ARTIFACT_OWNERSHIP]:
        assert entry.classification in OWNERSHIP_CLASSIFICATIONS
        assert entry.reason.strip()
        if entry.classification == "excluded_with_reason":
            assert entry.reason != "excluded"


def test_data_map_response_exposes_document_uploads_and_audio_policy() -> None:
    response = ownership_map_response()
    artifacts = {entry["name"]: entry for entry in response["artifacts"]}

    assert artifacts["document_uploads"]["classification"] == "owned_exportable"
    assert artifacts["recording_audio_staging"]["classification"] == "self_host_local"
    assert "deleted after processing" in artifacts["recording_audio_staging"]["reason"]
    assert response["audio_retention_policy"] == "delete_after_processing"


def test_agent_tables_are_classified_as_content_bearing() -> None:
    tables = {entry.name: entry for entry in DATA_OWNERSHIP}

    assert tables["agents"].contains_user_content is True
    assert tables["agent_runs"].contains_user_content is True
    assert tables["agent_steps"].contains_user_content is True
    assert tables["companion_pending_actions"].contains_user_content is True


def test_brain_space_tables_are_classified_for_self_host_export() -> None:
    tables = {entry.name: entry for entry in DATA_OWNERSHIP}

    assert tables["brain_spaces"].classification == "owned_exportable"
    assert tables["brain_pages"].contains_user_content is True
    assert tables["brain_claims"].contains_user_content is True
    assert tables["brain_review_packs"].contains_user_content is True


@pytest.mark.asyncio
async def test_system_data_map_route(client) -> None:
    response = await client.get("/api/system/data-map")

    assert response.status_code == 200
    payload = response.json()
    assert payload["audio_retention_policy"] == "delete_after_processing"
    assert any(row["table"] == "recordings" for row in payload["tables"])
