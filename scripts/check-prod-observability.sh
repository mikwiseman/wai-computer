#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${BASE_URL:-https://wai.computer}"
VPS_USER="${VPS_USER:-root}"
VPS_HOST="${VPS_HOST:-157.180.47.68}"
REMOTE_ROOT="${REMOTE_ROOT:-/opt/waicomputer}"
REMOTE_ENV_FILE="${REMOTE_ENV_FILE:-/etc/waicomputer/backend.env}"

check_url() {
  local label="$1"
  local url="$2"
  local expected="$3"
  local body
  body="$(curl -fsS --max-time 10 "$url")"
  if [[ "$body" != *"$expected"* ]]; then
    printf '%s failed: expected body to contain %s\n' "$label" "$expected" >&2
    return 1
  fi
  printf '%s ok\n' "$label"
}

check_url "health/live" "$BASE_URL/health/live" '"status":"alive"'
check_url "health/ready" "$BASE_URL/health/ready" '"status":"healthy"'

if [[ -n "${WAICOMPUTER_ACCESS_TOKEN:-}" ]]; then
  snapshot="$(
    curl -fsS --max-time 15 \
      -H "Authorization: Bearer ${WAICOMPUTER_ACCESS_TOKEN}" \
      "$BASE_URL/api/admin/observability"
  )"
  SNAPSHOT="$snapshot" python3 - <<'PY'
import json
import os

payload = json.loads(os.environ["SNAPSHOT"])
alerts = payload.get("alerts", [])
pipeline = payload.get("recording_pipeline", {})
print(
    "admin/observability ok "
    f"alerts={len(alerts)} "
    f"failed_rate_24h={pipeline.get('failed_rate_24h')} "
    f"stuck_processing={pipeline.get('stuck_processing_count')}"
)
if alerts:
    for item in alerts:
        print(f"alert {item.get('severity')} {item.get('code')} value={item.get('value')}")
PY
else
  printf 'admin/observability skipped: set WAICOMPUTER_ACCESS_TOKEN for authenticated snapshot\n'
fi

containers="$(
  ssh "${VPS_USER}@${VPS_HOST}" \
    "cd ${REMOTE_ROOT}/backend && docker compose --env-file ${REMOTE_ENV_FILE} ps --format json"
)"
CONTAINERS="$containers" python3 - <<'PY'
import json
import os
import sys

unhealthy = []
for line in os.environ["CONTAINERS"].splitlines():
    if not line.strip():
        continue
    item = json.loads(line)
    name = item.get("Name") or item.get("Service")
    state = item.get("State")
    health = item.get("Health") or "-"
    status = item.get("Status") or ""
    print(f"container {name} state={state} health={health} status={status}")
    if state != "running" or health not in {"healthy", "-"}:
        unhealthy.append(name)
if unhealthy:
    print("unhealthy containers: " + ", ".join(unhealthy), file=sys.stderr)
    raise SystemExit(1)
PY
