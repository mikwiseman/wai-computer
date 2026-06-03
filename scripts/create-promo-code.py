#!/usr/bin/env python3
"""Create a WaiComputer promo code on the production VPS.

The plaintext code is printed once. The database stores only its SHA-256 hash.
"""

from __future__ import annotations

import argparse
import os
import shlex
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = ROOT / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from app.billing.promo_codes import (  # noqa: E402
    generate_promo_code,
    hash_promo_code,
    normalize_promo_code,
)


def sql_string(value: str | None) -> str:
    if value is None:
        return "NULL"
    return "'" + value.replace("'", "''") + "'"


def build_sql(args: argparse.Namespace, code: str) -> str:
    expires_at = None
    if args.expires_days is not None:
        expires_at = (datetime.now(timezone.utc) + timedelta(days=args.expires_days)).isoformat()
    return f"""
DO $promo$
DECLARE
    target_plan_id uuid;
    new_code_id uuid;
BEGIN
    SELECT id INTO target_plan_id
    FROM billing_plans
    WHERE code = {sql_string(args.plan)};

    IF target_plan_id IS NULL THEN
        RAISE EXCEPTION 'Billing plan % not found', {sql_string(args.plan)};
    END IF;

    INSERT INTO billing_promo_codes (
        code,
        code_hash,
        plan_id,
        promotion_type,
        billing_period,
        duration_days,
        max_redemptions,
        expires_at,
        note
    )
    VALUES (
        {sql_string(code)},
        {sql_string(hash_promo_code(code))},
        target_plan_id,
        'access',
        {sql_string(args.period)},
        {args.duration_days},
        {args.max_redemptions},
        {sql_string(expires_at)},
        {sql_string(args.note)}
    )
    RETURNING id INTO new_code_id;

    RAISE NOTICE 'Created promo code id=%', new_code_id;
END
$promo$;
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
    parser = argparse.ArgumentParser(description="Create a WaiComputer promo code")
    parser.add_argument("--code", help="Specific plaintext code. Omit to generate one.")
    parser.add_argument("--prefix", default="WAI")
    parser.add_argument("--plan", default="pro")
    parser.add_argument("--period", choices=["month", "year"], default="month")
    parser.add_argument("--duration-days", type=int, default=30)
    parser.add_argument("--max-redemptions", type=int, default=1)
    parser.add_argument("--expires-days", type=int, default=30)
    parser.add_argument("--note")
    parser.add_argument("--vps-user", default=os.getenv("VPS_USER"))
    parser.add_argument("--vps-host", default=os.getenv("VPS_HOST"))
    parser.add_argument("--remote-root", default=os.getenv("REMOTE_ROOT"))
    parser.add_argument("--remote-env-file", default=os.getenv("REMOTE_ENV_FILE"))
    parser.add_argument(
        "--print-sql",
        action="store_true",
        help="Print SQL instead of executing it.",
    )
    args = parser.parse_args()

    if args.duration_days <= 0:
        raise SystemExit("--duration-days must be positive")
    if args.max_redemptions <= 0:
        raise SystemExit("--max-redemptions must be positive")

    code = args.code or generate_promo_code(prefix=args.prefix)
    if not normalize_promo_code(code):
        raise SystemExit("--code must contain letters or digits")
    sql = build_sql(args, code)

    if args.print_sql:
        print(sql)
        print(f"\nPlaintext promo code: {code}")
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

    output = run_on_vps(
        sql,
        user=args.vps_user,
        host=args.vps_host,
        root=args.remote_root,
        env_file=args.remote_env_file,
    )
    print(output.strip())
    print(f"Plaintext promo code: {code}")


if __name__ == "__main__":
    main()
