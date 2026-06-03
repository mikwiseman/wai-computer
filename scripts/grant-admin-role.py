#!/usr/bin/env python3
"""Grant a WaiComputer staff/admin role to an existing user email."""

from __future__ import annotations

import argparse
import os
import shlex
import subprocess
import sys


def sql_string(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def build_sql(*, email: str, role: str) -> str:
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
        RAISE EXCEPTION 'User email % not found', {sql_string(email)};
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

    RAISE NOTICE 'Granted % role to staff member %', {sql_string(role)}, target_staff_member_id;
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
    parser = argparse.ArgumentParser(description="Grant a WaiComputer staff/admin role")
    parser.add_argument("--email", required=True)
    parser.add_argument("--role", choices=["owner", "admin", "support"], default="owner")
    parser.add_argument("--vps-user", default=os.getenv("VPS_USER"))
    parser.add_argument("--vps-host", default=os.getenv("VPS_HOST"))
    parser.add_argument("--remote-root", default=os.getenv("REMOTE_ROOT"))
    parser.add_argument("--remote-env-file", default=os.getenv("REMOTE_ENV_FILE"))
    parser.add_argument("--print-sql", action="store_true")
    args = parser.parse_args()

    sql = build_sql(email=args.email.strip().lower(), role=args.role)
    if args.print_sql:
        print(sql)
        return
    missing = [
        name
        for name, value in [
            ("--vps-user/VPS_USER", args.vps_user),
            ("--vps-host/VPS_HOST", args.vps_host),
            ("--remote-root/REMOTE_ROOT", args.remote_root),
            ("--remote-env-file/REMOTE_ENV_FILE", args.remote_env_file),
        ]
        if not value
    ]
    if missing:
        raise SystemExit("Missing required deployment settings: " + ", ".join(missing))
    print(
        run_on_vps(
            sql,
            user=args.vps_user,
            host=args.vps_host,
            root=args.remote_root,
            env_file=args.remote_env_file,
        ).strip()
    )


if __name__ == "__main__":
    main()
