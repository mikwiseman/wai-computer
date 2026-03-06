"""Edge-case tests for API routes.

These tests exercise boundary conditions, unusual inputs, and cascade
behaviour against the real test database via the ``client`` / ``auth_headers``
fixtures from conftest.
"""


from httpx import AsyncClient

# ---------------------------------------------------------------------------
# 1. UUID injection / SQL-injection-like strings
# ---------------------------------------------------------------------------


async def test_uuid_injection_returns_422(client: AsyncClient, auth_headers: dict):
    """SQL-injection-like strings in place of a UUID path param yield 422."""
    malicious_ids = [
        "'; DROP TABLE recordings--",
        "1 OR 1=1",
        "<script>alert(1)</script>",
        "null",
        "../../../etc/passwd",
    ]
    for bad_id in malicious_ids:
        response = await client.get(f"/api/recordings/{bad_id}", headers=auth_headers)
        assert response.status_code in (404, 422), (
            f"Expected 404/422 for recording_id={bad_id!r}, got {response.status_code}"
        )


# ---------------------------------------------------------------------------
# 2. Long title accepted
# ---------------------------------------------------------------------------


async def test_long_title_accepted(client: AsyncClient, auth_headers: dict):
    """A 500-character title should be accepted (column is String(500))."""
    long_title = "A" * 500
    response = await client.post(
        "/api/recordings",
        json={"title": long_title, "type": "note"},
        headers=auth_headers,
    )
    assert response.status_code == 201
    data = response.json()
    assert data["title"] == long_title


# ---------------------------------------------------------------------------
# 3. Unicode / emoji in titles and entity names
# ---------------------------------------------------------------------------


async def test_unicode_emoji_recording_title(client: AsyncClient, auth_headers: dict):
    """Recording titles with emoji and CJK characters are stored correctly."""
    title = "\U0001f399\ufe0f Meeting Notes \u65e5\u672c\u8a9e \u2603\ufe0f"
    response = await client.post(
        "/api/recordings",
        json={"title": title, "type": "meeting"},
        headers=auth_headers,
    )
    assert response.status_code == 201
    data = response.json()
    assert data["title"] == title

    # Fetch it back to confirm round-trip
    rec_id = data["id"]
    get_resp = await client.get(f"/api/recordings/{rec_id}", headers=auth_headers)
    assert get_resp.status_code == 200
    assert get_resp.json()["title"] == title


async def test_unicode_entity_name(client: AsyncClient, auth_headers: dict):
    """Entity names with unicode characters are accepted and stored correctly."""
    name = "\u00c9mile Zola \u2014 \u4e16\u754c\u306e\u4eba"
    response = await client.post(
        "/api/entities",
        json={"type": "person", "name": name},
        headers=auth_headers,
    )
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == name


# ---------------------------------------------------------------------------
# 4. Cascade delete
# ---------------------------------------------------------------------------


async def test_cascade_delete_removes_recording(client: AsyncClient, auth_headers: dict):
    """Deleting a recording soft-deletes first, then permanent delete removes it.

    First delete sets ``deleted_at`` (soft delete / trash).
    Second delete with ``permanent=true`` or deleting a trashed recording
    hard-deletes it and cascades to segments, summary, and action items.
    """
    # Create recording
    create_resp = await client.post(
        "/api/recordings",
        json={"title": "Cascade Test", "type": "note"},
        headers=auth_headers,
    )
    assert create_resp.status_code == 201
    rec_id = create_resp.json()["id"]

    # Verify it exists
    get_resp = await client.get(f"/api/recordings/{rec_id}", headers=auth_headers)
    assert get_resp.status_code == 200
    assert get_resp.json()["deleted_at"] is None

    # Soft-delete it (move to trash)
    del_resp = await client.delete(f"/api/recordings/{rec_id}", headers=auth_headers)
    assert del_resp.status_code == 204

    # Verify it is soft-deleted (still accessible but has deleted_at)
    get_resp2 = await client.get(f"/api/recordings/{rec_id}", headers=auth_headers)
    assert get_resp2.status_code == 200
    assert get_resp2.json()["deleted_at"] is not None

    # Permanently delete it (already trashed, so second delete is permanent)
    del_resp2 = await client.delete(f"/api/recordings/{rec_id}", headers=auth_headers)
    assert del_resp2.status_code == 204

    # Verify it is gone
    get_resp3 = await client.get(f"/api/recordings/{rec_id}", headers=auth_headers)
    assert get_resp3.status_code == 404


# ---------------------------------------------------------------------------
# 4b. Restore from trash
# ---------------------------------------------------------------------------


async def test_restore_recording_from_trash(client: AsyncClient, auth_headers: dict):
    """Soft-deleted recordings can be restored."""
    create_resp = await client.post(
        "/api/recordings",
        json={"title": "Restore Me", "type": "note"},
        headers=auth_headers,
    )
    rec_id = create_resp.json()["id"]

    # Soft-delete
    await client.delete(f"/api/recordings/{rec_id}", headers=auth_headers)

    # Appears in trash list
    trash_resp = await client.get("/api/recordings?trashed=true", headers=auth_headers)
    assert any(r["id"] == rec_id for r in trash_resp.json())

    # Not in normal list
    normal_resp = await client.get("/api/recordings", headers=auth_headers)
    assert all(r["id"] != rec_id for r in normal_resp.json())

    # Restore
    restore_resp = await client.post(
        f"/api/recordings/{rec_id}/restore", headers=auth_headers
    )
    assert restore_resp.status_code == 200
    assert restore_resp.json()["deleted_at"] is None

    # Back in normal list
    normal_resp2 = await client.get("/api/recordings", headers=auth_headers)
    assert any(r["id"] == rec_id for r in normal_resp2.json())


async def test_restore_nonexistent_recording_404(client: AsyncClient, auth_headers: dict):
    resp = await client.post(
        "/api/recordings/00000000-0000-0000-0000-000000000000/restore",
        headers=auth_headers,
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# 5. Max limit enforcement
# ---------------------------------------------------------------------------


async def test_limit_above_max_returns_422(client: AsyncClient, auth_headers: dict):
    """The list-recordings endpoint enforces ``le=200`` on the limit param.

    Requesting ``limit=201`` should return 422 (validation error).
    """
    response = await client.get(
        "/api/recordings?limit=201",
        headers=auth_headers,
    )
    assert response.status_code == 422


async def test_limit_at_max_boundary_succeeds(client: AsyncClient, auth_headers: dict):
    """Requesting exactly the maximum allowed limit (200) should succeed."""
    response = await client.get(
        "/api/recordings?limit=200",
        headers=auth_headers,
    )
    assert response.status_code == 200


async def test_limit_zero_returns_422(client: AsyncClient, auth_headers: dict):
    """Requesting ``limit=0`` violates ``ge=1`` and should return 422."""
    response = await client.get(
        "/api/recordings?limit=0",
        headers=auth_headers,
    )
    assert response.status_code == 422


async def test_negative_skip_returns_422(client: AsyncClient, auth_headers: dict):
    """Requesting ``skip=-1`` violates ``ge=0`` and should return 422."""
    response = await client.get(
        "/api/recordings?skip=-1",
        headers=auth_headers,
    )
    assert response.status_code == 422
