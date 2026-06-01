"""Tests for MCP connection models + secret encryption (Phase: connect-any-MCP)."""

from app.core.secrets_crypto import decrypt_secret, encrypt_secret
from app.models import Base, McpConnection, McpIngestionRun


def test_tables_registered() -> None:
    assert "mcp_connections" in Base.metadata.tables
    assert "mcp_ingestion_runs" in Base.metadata.tables
    assert McpConnection.__tablename__ == "mcp_connections"
    assert McpIngestionRun.__tablename__ == "mcp_ingestion_runs"


def test_connection_required_columns() -> None:
    cols = Base.metadata.tables["mcp_connections"].columns
    for required in ("user_id", "server_label", "server_url", "transport", "auth_type"):
        assert cols[required].nullable is False, required
    # Token blob is optional (a `none` auth server needs no secret).
    assert cols["auth_secret_encrypted"].nullable is True


def test_connection_unique_per_user_url() -> None:
    names = {c.name for c in Base.metadata.tables["mcp_connections"].constraints if c.name}
    assert "uq_mcp_connections_user_url" in names


def test_ingestion_run_columns() -> None:
    cols = Base.metadata.tables["mcp_ingestion_runs"].columns
    for c in ("connection_id", "status", "items_seen", "items_created", "started_at"):
        assert c in cols


def test_secret_encryption_roundtrip() -> None:
    token = encrypt_secret("wc_live_supersecret")
    assert token != "wc_live_supersecret"  # actually encrypted
    assert decrypt_secret(token) == "wc_live_supersecret"


def test_secret_encryption_is_nondeterministic() -> None:
    # Fernet embeds a random IV + timestamp, so two encryptions differ.
    a = encrypt_secret("same")
    b = encrypt_secret("same")
    assert a != b
    assert decrypt_secret(a) == decrypt_secret(b) == "same"
