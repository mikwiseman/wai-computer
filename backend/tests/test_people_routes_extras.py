"""Branch tests for /api/people not covered by test_people_routes.py."""

from __future__ import annotations

from uuid import uuid4


async def _register(client) -> tuple[dict, str]:
    """Register a fresh user; returns (auth_headers, email)."""
    email = f"people-extra-{uuid4().hex}@example.com"
    resp = await client.post(
        "/api/auth/register",
        json={"email": email, "password": "testpassword123"},
    )
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}, email


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


async def test_create_person_with_aliases(client) -> None:
    """Aliases are serialized as a list of strings on the response."""
    auth, _ = await _register(client)
    resp = await client.post(
        "/api/people",
        json={"display_name": "Vasya", "aliases": ["V", "Vas"]},
        headers=auth,
    )
    assert resp.status_code == 201
    assert resp.json()["aliases"] == ["V", "Vas"]


async def test_create_person_empty_aliases_serializes_as_null(client) -> None:
    auth, _ = await _register(client)
    resp = await client.post(
        "/api/people", json={"display_name": "Vasya"}, headers=auth,
    )
    assert resp.status_code == 201
    assert resp.json()["aliases"] is None


async def test_update_person_blank_display_name_rejected(client) -> None:
    auth, _ = await _register(client)
    create = await client.post(
        "/api/people", json={"display_name": "Original"}, headers=auth,
    )
    person_id = create.json()["id"]
    resp = await client.patch(
        f"/api/people/{person_id}",
        json={"display_name": "   "},  # whitespace-only triggers validator
        headers=auth,
    )
    assert resp.status_code == 422


async def test_update_person_null_display_name_preserves(client) -> None:
    """Passing display_name=null leaves it unchanged (validator early-returns
    None for None input)."""
    auth, _ = await _register(client)
    create = await client.post(
        "/api/people", json={"display_name": "Keeps"}, headers=auth,
    )
    person_id = create.json()["id"]
    # Update only color, leave display_name absent (None default)
    resp = await client.patch(
        f"/api/people/{person_id}", json={"color": "#000000"}, headers=auth,
    )
    assert resp.status_code == 200
    assert resp.json()["display_name"] == "Keeps"
    assert resp.json()["color"] == "#000000"


async def test_update_person_aliases(client) -> None:
    auth, _ = await _register(client)
    create = await client.post(
        "/api/people", json={"display_name": "Vasya"}, headers=auth,
    )
    person_id = create.json()["id"]

    resp = await client.patch(
        f"/api/people/{person_id}",
        json={"aliases": ["V", "Vasily"]},
        headers=auth,
    )
    assert resp.status_code == 200
    assert resp.json()["aliases"] == ["V", "Vasily"]


# ---------------------------------------------------------------------------
# 404 / not-found branches
# ---------------------------------------------------------------------------


async def test_update_person_returns_404_for_unknown(client) -> None:
    auth, _ = await _register(client)
    resp = await client.patch(
        f"/api/people/{uuid4()}",
        json={"display_name": "Ghost"},
        headers=auth,
    )
    assert resp.status_code == 404


async def test_delete_person_returns_404_for_unknown(client) -> None:
    auth, _ = await _register(client)
    resp = await client.delete(f"/api/people/{uuid4()}", headers=auth)
    assert resp.status_code == 404


async def test_update_person_returns_404_for_other_user(client) -> None:
    """Per-user isolation: another user's person id returns 404, not 403."""
    auth_a, _ = await _register(client)
    create = await client.post(
        "/api/people", json={"display_name": "A's person"}, headers=auth_a,
    )
    person_id = create.json()["id"]

    auth_b, _ = await _register(client)
    resp = await client.patch(
        f"/api/people/{person_id}",
        json={"display_name": "stolen"},
        headers=auth_b,
    )
    assert resp.status_code == 404


async def test_delete_person_returns_404_for_other_user(client) -> None:
    auth_a, _ = await _register(client)
    create = await client.post(
        "/api/people", json={"display_name": "A's person"}, headers=auth_a,
    )
    person_id = create.json()["id"]

    auth_b, _ = await _register(client)
    resp = await client.delete(f"/api/people/{person_id}", headers=auth_b)
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Merge edge cases
# ---------------------------------------------------------------------------


async def test_merge_into_self_rejected(client) -> None:
    auth, _ = await _register(client)
    create = await client.post(
        "/api/people", json={"display_name": "Solo"}, headers=auth,
    )
    person_id = create.json()["id"]
    resp = await client.post(
        f"/api/people/{person_id}/merge",
        json={"into_person_id": person_id},
        headers=auth,
    )
    assert resp.status_code == 400
    assert "itself" in resp.json()["detail"]


async def test_merge_returns_404_when_source_missing(client) -> None:
    auth, _ = await _register(client)
    target = await client.post(
        "/api/people", json={"display_name": "Target"}, headers=auth,
    )
    target_id = target.json()["id"]
    resp = await client.post(
        f"/api/people/{uuid4()}/merge",
        json={"into_person_id": target_id},
        headers=auth,
    )
    assert resp.status_code == 404


async def test_merge_returns_404_when_target_missing(client) -> None:
    auth, _ = await _register(client)
    source = await client.post(
        "/api/people", json={"display_name": "Source"}, headers=auth,
    )
    source_id = source.json()["id"]
    resp = await client.post(
        f"/api/people/{source_id}/merge",
        json={"into_person_id": str(uuid4())},
        headers=auth,
    )
    assert resp.status_code == 404


async def test_list_people_empty_for_new_user(client) -> None:
    auth, _ = await _register(client)
    resp = await client.get("/api/people", headers=auth)
    assert resp.status_code == 200
    assert resp.json() == []
