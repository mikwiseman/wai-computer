"""Live API integration tests against the deployed server.

Run with: pytest -q -m integration --no-cov
Requires: LIVE_API_URL env var (default: https://say.waiwai.is)

These tests hit the REAL deployed API. Each test creates unique users with
timestamped emails and cleans up all resources it creates. Tests are fully
independent of each other -- no shared state between tests.
"""

import asyncio
import os
import time

import httpx
import pytest

BASE_URL = os.getenv("LIVE_API_URL", "https://say.waiwai.is")
REGISTER_INTERVAL_SECONDS = float(os.getenv("LIVE_REGISTER_INTERVAL_SECONDS", "21.5"))
REGISTER_LIMIT_WINDOW_SECONDS = float(os.getenv("LIVE_REGISTER_LIMIT_WINDOW_SECONDS", "61.0"))

pytestmark = pytest.mark.integration

_register_lock = asyncio.Lock()
_last_register_at = 0.0


def make_test_email(name: str) -> str:
    """Generate a unique test email address."""
    return f"test.{name}.{int(time.time())}@example.com"


TEST_PASSWORD = "TestP@ssw0rd123!"


def auth_header(token: str) -> dict[str, str]:
    """Build an Authorization header from a token."""
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def register_user(
    client: httpx.AsyncClient,
    email: str,
    password: str = TEST_PASSWORD,
) -> str:
    """Register a user and return the access token."""
    for attempt in range(2):
        await wait_for_register_slot()
        resp = await client.post(
            "/api/auth/register",
            json={"email": email, "password": password},
        )
        if resp.status_code != 429 or attempt == 1:
            break
        await asyncio.sleep(REGISTER_LIMIT_WINDOW_SECONDS)

    assert resp.status_code == 200, f"Register failed: {resp.status_code} {resp.text}"
    data = resp.json()
    assert data["token_type"] == "bearer"
    return data["access_token"]


async def wait_for_register_slot() -> None:
    """Pace live account creation so integration tests respect prod rate limits."""
    global _last_register_at

    if REGISTER_INTERVAL_SECONDS <= 0:
        return

    async with _register_lock:
        now = time.monotonic()
        wait_seconds = REGISTER_INTERVAL_SECONDS - (now - _last_register_at)
        if wait_seconds > 0:
            await asyncio.sleep(wait_seconds)
        _last_register_at = time.monotonic()


async def login_user(
    client: httpx.AsyncClient,
    email: str,
    password: str = TEST_PASSWORD,
) -> str:
    """Login and return the access token."""
    resp = await client.post(
        "/api/auth/login",
        json={"email": email, "password": password},
    )
    assert resp.status_code == 200, f"Login failed: {resp.status_code} {resp.text}"
    return resp.json()["access_token"]


async def create_recording(
    client: httpx.AsyncClient,
    token: str,
    title: str | None = None,
    rec_type: str = "note",
) -> dict:
    """Create a recording and return the response body."""
    body: dict = {"type": rec_type}
    if title is not None:
        body["title"] = title
    resp = await client.post(
        "/api/recordings",
        json=body,
        headers=auth_header(token),
    )
    assert resp.status_code == 201, f"Create recording failed: {resp.status_code} {resp.text}"
    return resp.json()


async def delete_recording(
    client: httpx.AsyncClient,
    token: str,
    recording_id: str,
) -> None:
    """Delete a recording (best-effort cleanup)."""
    await client.delete(
        f"/api/recordings/{recording_id}?permanent=true",
        headers=auth_header(token),
    )


async def create_entity(
    client: httpx.AsyncClient,
    token: str,
    name: str,
    entity_type: str = "person",
    metadata: dict | None = None,
) -> dict:
    """Create an entity and return the response body."""
    body: dict = {"name": name, "type": entity_type}
    if metadata is not None:
        body["metadata"] = metadata
    resp = await client.post(
        "/api/entities",
        json=body,
        headers=auth_header(token),
    )
    assert resp.status_code == 201, f"Create entity failed: {resp.status_code} {resp.text}"
    return resp.json()


async def delete_entity(
    client: httpx.AsyncClient,
    token: str,
    entity_id: str,
) -> None:
    """Delete an entity (best-effort cleanup)."""
    await client.delete(
        f"/api/entities/{entity_id}",
        headers=auth_header(token),
    )


# ---------------------------------------------------------------------------
# 1. Health endpoints
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_health_endpoints():
    """GET / serves the web app and GET /health returns healthy API status."""
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=15) as client:
        # Root is the web app on the canonical production host.
        resp = await client.get("/")
        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("content-type", "")
        assert "WaiSay" in resp.text

        # Health
        resp = await client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "healthy"
        assert data["database"] == "connected"


# ---------------------------------------------------------------------------
# 2. Auth lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_auth_lifecycle():
    """Register -> /me -> login -> new token -> logout -> cookie cleared."""
    email = make_test_email("auth_lifecycle")

    async with httpx.AsyncClient(base_url=BASE_URL, timeout=15) as client:
        # Register
        token = await register_user(client, email)

        # GET /me
        resp = await client.get("/api/auth/me", headers=auth_header(token))
        assert resp.status_code == 200
        me = resp.json()
        assert me["email"] == email
        assert "id" in me
        assert "created_at" in me

        # Login with same creds -> new token
        token2 = await login_user(client, email)
        assert token2  # non-empty
        # Token should still work
        resp = await client.get("/api/auth/me", headers=auth_header(token2))
        assert resp.status_code == 200

        # Logout
        resp = await client.post("/api/auth/logout", headers=auth_header(token2))
        assert resp.status_code == 200
        # Verify Set-Cookie clears the auth cookie
        set_cookie = resp.headers.get("set-cookie", "")
        assert "wai_access_token" in set_cookie


# ---------------------------------------------------------------------------
# 3. Duplicate registration -> 400
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_duplicate_registration():
    """Registering the same email twice returns 400."""
    email = make_test_email("dup_reg")

    async with httpx.AsyncClient(base_url=BASE_URL, timeout=15) as client:
        await register_user(client, email)

        resp = await client.post(
            "/api/auth/register",
            json={"email": email, "password": TEST_PASSWORD},
        )
        assert resp.status_code == 400
        assert (
            resp.json()["detail"]
            == "Unable to create account. Try signing in or request a magic link."
        )


# ---------------------------------------------------------------------------
# 4. Wrong password login -> 401
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_wrong_password_login():
    """Login with incorrect password returns 401."""
    email = make_test_email("wrong_pw")

    async with httpx.AsyncClient(base_url=BASE_URL, timeout=15) as client:
        await register_user(client, email)

        resp = await client.post(
            "/api/auth/login",
            json={"email": email, "password": "WrongPassword999!"},
        )
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# 5. Magic link request -> 200 and invalid verify -> 401
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_magic_link_and_invalid_verify():
    """POST /api/auth/magic-link returns 200. Invalid token verify returns 401."""
    email = make_test_email("magic")

    async with httpx.AsyncClient(base_url=BASE_URL, timeout=15) as client:
        # Request magic link -- the server will attempt to send an email.
        # With @example.com, Resend may reject it, but the endpoint should
        # either succeed (200) or fail with a server error. We accept 200 or
        # 500 here since the email delivery is external and not under test.
        resp = await client.post(
            "/api/auth/magic-link",
            json={"email": email},
        )
        # We primarily test that the endpoint exists and handles the request.
        # A 200 means it succeeded; a 500 means email delivery failed but the
        # route itself is wired correctly. Both are acceptable for this test.
        assert resp.status_code in (200, 500), (
            f"Unexpected status from magic-link: {resp.status_code} {resp.text}"
        )

        # Verify with a bogus token -> 401
        resp = await client.post(
            "/api/auth/verify-magic",
            json={"token": "bogus-token-that-does-not-exist"},
        )
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# 6. Recording CRUD
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recording_crud():
    """Create -> list -> get detail -> update title -> get transcript -> delete -> 404."""
    email = make_test_email("rec_crud")

    async with httpx.AsyncClient(base_url=BASE_URL, timeout=15) as client:
        token = await register_user(client, email)
        headers = auth_header(token)

        # Create
        rec = await create_recording(client, token, title="Integration Test Recording")
        rec_id = rec["id"]
        assert rec["title"] == "Integration Test Recording"
        assert rec["type"] == "note"

        try:
            # List recordings
            resp = await client.get("/api/recordings", headers=headers)
            assert resp.status_code == 200
            recs = resp.json()
            assert isinstance(recs, list)
            assert any(r["id"] == rec_id for r in recs)

            # Get detail
            resp = await client.get(f"/api/recordings/{rec_id}", headers=headers)
            assert resp.status_code == 200
            detail = resp.json()
            assert detail["id"] == rec_id
            assert "segments" in detail
            assert "summary" in detail
            assert "action_items" in detail

            # Update title (PATCH)
            resp = await client.patch(
                f"/api/recordings/{rec_id}",
                json={"title": "Updated Title"},
                headers=headers,
            )
            assert resp.status_code == 200
            assert resp.json()["title"] == "Updated Title"

            # Get transcript (empty list is fine -- no audio uploaded)
            resp = await client.get(f"/api/recordings/{rec_id}/transcript", headers=headers)
            assert resp.status_code == 200
            assert isinstance(resp.json(), list)

            # Delete
            resp = await client.delete(f"/api/recordings/{rec_id}", headers=headers)
            assert resp.status_code == 204

            # Regular delete is soft-delete: detail remains readable, but marked deleted.
            resp = await client.get(f"/api/recordings/{rec_id}", headers=headers)
            assert resp.status_code == 200
            assert resp.json()["deleted_at"] is not None

            # Permanent delete removes it completely.
            resp = await client.delete(
                f"/api/recordings/{rec_id}?permanent=true",
                headers=headers,
            )
            assert resp.status_code == 204
            resp = await client.get(f"/api/recordings/{rec_id}", headers=headers)
            assert resp.status_code == 404

        except Exception:
            # Cleanup on failure
            await delete_recording(client, token, rec_id)
            raise


# ---------------------------------------------------------------------------
# 7. Recording type filtering
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recording_type_filtering():
    """Create 3 recordings of different types and filter by each type."""
    email = make_test_email("rec_filter")
    created_ids: list[str] = []

    async with httpx.AsyncClient(base_url=BASE_URL, timeout=15) as client:
        token = await register_user(client, email)
        headers = auth_header(token)

        try:
            for rec_type in ("meeting", "note", "reflection"):
                rec = await create_recording(
                    client,
                    token,
                    title=f"Filter test {rec_type}",
                    rec_type=rec_type,
                )
                created_ids.append(rec["id"])

            # Filter by each type
            for rec_type in ("meeting", "note", "reflection"):
                resp = await client.get(
                    "/api/recordings",
                    params={"type": rec_type},
                    headers=headers,
                )
                assert resp.status_code == 200
                recs = resp.json()
                assert len(recs) == 1, f"Expected 1 {rec_type}, got {len(recs)}"
                assert recs[0]["type"] == rec_type

        finally:
            for rid in created_ids:
                await delete_recording(client, token, rid)


# ---------------------------------------------------------------------------
# 8. Search endpoints (shape validation)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_endpoints():
    """All three search endpoints return 200 with correct response shape."""
    email = make_test_email("search")

    async with httpx.AsyncClient(base_url=BASE_URL, timeout=15) as client:
        token = await register_user(client, email)
        headers = auth_header(token)

        # Create a recording so the user exists in the system
        rec = await create_recording(client, token, title="Search test")

        try:
            # Hybrid search
            resp = await client.get(
                "/api/search",
                params={"q": "test"},
                headers=headers,
            )
            assert resp.status_code == 200
            data = resp.json()
            assert "results" in data
            assert "total" in data
            assert isinstance(data["results"], list)
            assert isinstance(data["total"], int)

            # Semantic search
            resp = await client.get(
                "/api/search/semantic",
                params={"q": "test"},
                headers=headers,
            )
            assert resp.status_code == 200
            data = resp.json()
            assert "results" in data
            assert "total" in data

            # Full-text search
            resp = await client.get(
                "/api/search/fts",
                params={"q": "test"},
                headers=headers,
            )
            assert resp.status_code == 200
            data = resp.json()
            assert "results" in data
            assert "total" in data

        finally:
            await delete_recording(client, token, rec["id"])


# ---------------------------------------------------------------------------
# 9. Entity CRUD
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_entity_crud():
    """Create -> list -> filter by type -> get detail -> delete -> 404."""
    email = make_test_email("entity_crud")

    async with httpx.AsyncClient(base_url=BASE_URL, timeout=15) as client:
        token = await register_user(client, email)
        headers = auth_header(token)

        # Create
        entity = await create_entity(
            client,
            token,
            name="Test Person",
            entity_type="person",
            metadata={"role": "engineer"},
        )
        entity_id = entity["id"]
        assert entity["name"] == "Test Person"
        assert entity["type"] == "person"
        assert entity["metadata"] == {"role": "engineer"}

        try:
            # List all entities
            resp = await client.get("/api/entities", headers=headers)
            assert resp.status_code == 200
            entities = resp.json()
            assert isinstance(entities, list)
            assert any(e["id"] == entity_id for e in entities)

            # Filter by type
            resp = await client.get(
                "/api/entities",
                params={"type": "person"},
                headers=headers,
            )
            assert resp.status_code == 200
            entities = resp.json()
            assert len(entities) >= 1
            assert all(e["type"] == "person" for e in entities)

            # Get detail
            resp = await client.get(f"/api/entities/{entity_id}", headers=headers)
            assert resp.status_code == 200
            detail = resp.json()
            assert detail["id"] == entity_id
            assert detail["name"] == "Test Person"
            assert "relations" in detail
            assert isinstance(detail["relations"], list)

            # Delete
            resp = await client.delete(f"/api/entities/{entity_id}", headers=headers)
            assert resp.status_code == 204

            # Verify gone
            resp = await client.get(f"/api/entities/{entity_id}", headers=headers)
            assert resp.status_code == 404

        except Exception:
            await delete_entity(client, token, entity_id)
            raise


# ---------------------------------------------------------------------------
# 10. Entity isolation between users
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_entity_isolation():
    """User B cannot see User A's entities."""
    email_a = make_test_email("iso_a")
    email_b = make_test_email("iso_b")

    async with httpx.AsyncClient(base_url=BASE_URL, timeout=15) as client:
        token_a = await register_user(client, email_a)
        token_b = await register_user(client, email_b)

        # User A creates an entity
        entity = await create_entity(client, token_a, name="Secret Entity", entity_type="project")
        entity_id = entity["id"]

        try:
            # User B tries to GET User A's entity -> 404
            resp = await client.get(
                f"/api/entities/{entity_id}",
                headers=auth_header(token_b),
            )
            assert resp.status_code == 404

            # User B's entity list should not contain User A's entity
            resp = await client.get("/api/entities", headers=auth_header(token_b))
            assert resp.status_code == 200
            b_entities = resp.json()
            assert not any(e["id"] == entity_id for e in b_entities)

        finally:
            await delete_entity(client, token_a, entity_id)


# ---------------------------------------------------------------------------
# 11. Action items
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_action_items_list():
    """GET /api/action-items returns 200 with a list."""
    email = make_test_email("action_items")

    async with httpx.AsyncClient(base_url=BASE_URL, timeout=15) as client:
        token = await register_user(client, email)
        headers = auth_header(token)

        resp = await client.get("/api/action-items", headers=headers)
        assert resp.status_code == 200
        items = resp.json()
        assert isinstance(items, list)


# ---------------------------------------------------------------------------
# 12. Password change
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_password_change():
    """Change password -> old password fails -> new password works."""
    email = make_test_email("pw_change")
    new_password = "NewP@ssw0rd456!"

    async with httpx.AsyncClient(base_url=BASE_URL, timeout=15) as client:
        token = await register_user(client, email)

        # Change password
        resp = await client.post(
            "/api/settings/change-password",
            json={
                "current_password": TEST_PASSWORD,
                "new_password": new_password,
            },
            headers=auth_header(token),
        )
        assert resp.status_code == 200
        msg = resp.json()["message"].lower()
        assert "changed" in msg or "set" in msg

        # Login with old password -> 401
        resp = await client.post(
            "/api/auth/login",
            json={"email": email, "password": TEST_PASSWORD},
        )
        assert resp.status_code == 401

        # Login with new password -> 200
        token2 = await login_user(client, email, password=new_password)
        assert token2


# ---------------------------------------------------------------------------
# 13. CORS headers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cors_headers():
    """OPTIONS preflight to /api/auth/login with allowed origin returns CORS headers."""
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=15) as client:
        resp = await client.options(
            "/api/auth/login",
            headers={
                "Origin": "https://say.waiwai.is",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "Authorization, Content-Type",
            },
        )
        # FastAPI CORS middleware returns 200 for preflight requests
        assert resp.status_code == 200

        assert resp.headers.get("access-control-allow-origin") == "https://say.waiwai.is"
        assert "POST" in resp.headers.get("access-control-allow-methods", "")
        assert "authorization" in resp.headers.get("access-control-allow-headers", "").lower()
