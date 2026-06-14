#!/usr/bin/env python3
"""Create a dedicated WaiComputer staff/admin login on the production VPS."""

from __future__ import annotations

import argparse
import secrets
import shlex
import subprocess
import sys

import bcrypt

LEGAL_VERSION = "2026-05-22"


def bcrypt_password_hash(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8")[:72], bcrypt.gensalt()).decode("ascii")


def sql_string(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def build_sql(
    *,
    email: str,
    password_hash: str,
    role: str,
    reset_existing_password: bool,
) -> str:
    reset_sql = "TRUE" if reset_existing_password else "FALSE"
    return f"""
DO $admin$
DECLARE
    target_user_id uuid;
    target_staff_member_id uuid;
BEGIN
    SELECT id INTO target_user_id
    FROM users
    WHERE email = {sql_string(email)};

    IF target_user_id IS NULL THEN
        INSERT INTO users (
            email,
            password_hash,
            account_status,
            legal_terms_accepted_at,
            legal_terms_version,
            legal_privacy_version,
            legal_acceptance_source
        )
        VALUES (
            {sql_string(email)},
            {sql_string(password_hash)},
            'active',
            now(),
            {sql_string(LEGAL_VERSION)},
            {sql_string(LEGAL_VERSION)},
            'admin_bootstrap'
        )
        RETURNING id INTO target_user_id;
    ELSIF {reset_sql} THEN
        UPDATE users
        SET password_hash = {sql_string(password_hash)},
            magic_link_token = NULL,
            magic_link_expires = NULL,
            account_status = 'active',
            account_status_reason = NULL,
            account_status_changed_at = now(),
            legal_terms_accepted_at = COALESCE(legal_terms_accepted_at, now()),
            legal_terms_version = COALESCE(legal_terms_version, {sql_string(LEGAL_VERSION)}),
            legal_privacy_version = COALESCE(legal_privacy_version, {sql_string(LEGAL_VERSION)}),
            legal_acceptance_source = COALESCE(legal_acceptance_source, 'admin_bootstrap'),
            updated_at = now()
        WHERE id = target_user_id;
    ELSE
        RAISE EXCEPTION
            'User email % already exists; use grant-admin-role.py or --reset-existing-password',
            {sql_string(email)};
    END IF;

    INSERT INTO staff_members (user_id, status)
    VALUES (target_user_id, 'active')
    ON CONFLICT (user_id)
    DO UPDATE SET status = 'active', updated_at = now()
    RETURNING id INTO target_staff_member_id;

    INSERT INTO admin_roles (staff_member_id, role)
    VALUES (target_staff_member_id, {sql_string(role)})
    ON CONFLICT (staff_member_id, role)
    DO UPDATE SET revoked_at = NULL, updated_at = now();

    RAISE NOTICE 'Registered admin user % staff member %', target_user_id, target_staff_member_id;
END
$admin$;
""".strip()


def run_on_vps(sql: str, *, user: str, host: str, root: str, env_file: str) -> str:
    quoted_sql = shlex.quote(sql)
    psql_command = shlex.quote(
        'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 -c "$1"'
    )
    remote = (
        f"cd {shlex.quote(root)}/backend && "
        f"docker compose --env-file {shlex.quote(env_file)} exec -T db "
        f"sh -c {psql_command} sh {quoted_sql}"
    )
    result = subprocess.run(
        ["ssh", f"{user}@{host}", remote],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        sys.stderr.write(result.stderr)
        raise SystemExit(result.returncode)
    return result.stdout


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a WaiComputer staff/admin login")
    parser.add_argument("--email", required=True)
    parser.add_argument("--role", choices=["owner", "admin", "support"], default="owner")
    parser.add_argument("--password")
    parser.add_argument("--reset-existing-password", action="store_true")
    parser.add_argument("--vps-user", default="root")
    parser.add_argument("--vps-host", default="157.180.47.68")
    parser.add_argument("--remote-root", default="/opt/waicomputer")
    parser.add_argument("--remote-env-file", default="/etc/waicomputer/backend.env")
    parser.add_argument("--print-sql", action="store_true")
    args = parser.parse_args()

    password = args.password or secrets.token_urlsafe(18)
    if len(password.strip()) < 12:
        raise SystemExit("--password must be at least 12 characters")

    email = args.email.strip().lower()
    sql = build_sql(
        email=email,
        password_hash=bcrypt_password_hash(password),
        role=args.role,
        reset_existing_password=args.reset_existing_password,
    )
    if args.print_sql:
        print(sql)
        print(f"\nAdmin login: {email}")
        print(f"Admin password: {password}")
        return

    print(
        run_on_vps(
            sql,
            user=args.vps_user,
            host=args.vps_host,
            root=args.remote_root,
            env_file=args.remote_env_file,
        ).strip()
    )
    print(f"Admin login: {email}")
    print(f"Admin password: {password}")


if __name__ == "__main__":
    main()
