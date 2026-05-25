"""Tests for the production promo-code helper script."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace


def _load_script_module(filename: str = "create-promo-code.py"):
    script_path = Path(__file__).resolve().parents[2] / "scripts" / filename
    module_name = filename.removesuffix(".py").replace("-", "_")
    spec = importlib.util.spec_from_file_location(module_name, script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_run_on_vps_reads_postgres_env_inside_db_container(monkeypatch):
    script = _load_script_module()
    captured: dict[str, list[str]] = {}

    def fake_run(args, *, text, capture_output, check):
        captured["args"] = args
        assert text is True
        assert capture_output is True
        assert check is False
        return SimpleNamespace(returncode=0, stdout="ok\n", stderr="")

    monkeypatch.setattr(script.subprocess, "run", fake_run)

    output = script.run_on_vps(
        "SELECT '$POSTGRES_USER';",
        user="deploy",
        host="example.com",
        root="/srv/wai computer",
        env_file="/etc/wai computer/backend.env",
    )

    assert output == "ok\n"
    assert captured["args"][:2] == ["ssh", "deploy@example.com"]
    remote_command = captured["args"][2]
    assert "docker compose --env-file '/etc/wai computer/backend.env' exec -T db sh -c" in (
        remote_command
    )
    assert 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"' in remote_command
    assert "exec -T db psql -U" not in remote_command


def test_grant_admin_role_script_targets_staff_members():
    script = _load_script_module("grant-admin-role.py")

    sql = script.build_sql(email="admin@example.com", role="owner")

    assert "INSERT INTO staff_members (user_id, status)" in sql
    assert "INSERT INTO admin_roles (staff_member_id, role)" in sql
    assert "ON CONFLICT (staff_member_id, role)" in sql
    assert "admin_roles (user_id, role)" not in sql


def test_create_admin_user_script_requires_explicit_existing_password_reset():
    script = _load_script_module("create-admin-user.py")

    sql = script.build_sql(
        email="admin@example.com",
        password_hash="$2b$12$example",
        role="owner",
        reset_existing_password=False,
    )

    assert "INSERT INTO users" in sql
    assert "INSERT INTO staff_members (user_id, status)" in sql
    assert "INSERT INTO admin_roles (staff_member_id, role)" in sql
    assert "User email % already exists" in sql
    assert "ELSIF FALSE THEN" in sql
