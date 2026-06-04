#!/usr/bin/env bash
# Basic API smoke test for WaiComputer.
# Usage: BASE_URL=https://wai.computer ./scripts/api-smoke.sh

set -euo pipefail

BASE_URL="${BASE_URL:-https://wai.computer}"
RUN_ID="$(date +%s)"
EMAIL_PREFIX="${EMAIL_PREFIX:-qa.smoke}"
EMAIL="${EMAIL_PREFIX}.${RUN_ID}@example.com"
PASSWORD="${PASSWORD:-Passw0rd!234}"
NEW_PASSWORD="${NEW_PASSWORD:-Passw0rd!567}"
LEGAL_TERMS_VERSION="${LEGAL_TERMS_VERSION:-2026-05-22}"
LEGAL_PRIVACY_VERSION="${LEGAL_PRIVACY_VERSION:-2026-05-22}"

http_json() {
  local method="$1"
  local url="$2"
  local token="${3:-}"
  local body="${4:-}"

  if [[ -n "$token" && -n "$body" ]]; then
    curl -sS -X "$method" "$url" \
      -H "Authorization: Bearer $token" \
      -H "Content-Type: application/json" \
      -d "$body"
  elif [[ -n "$token" ]]; then
    curl -sS -X "$method" "$url" \
      -H "Authorization: Bearer $token"
  elif [[ -n "$body" ]]; then
    curl -sS -X "$method" "$url" \
      -H "Content-Type: application/json" \
      -d "$body"
  else
    curl -sS -X "$method" "$url"
  fi
}

extract_json() {
  local json="$1"
  local path="$2"
  python3 - <<'PY' "$json" "$path"
import json
import sys

obj = json.loads(sys.argv[1])
path = sys.argv[2].split(".")
cur = obj
for p in path:
    cur = cur[p]
print(cur)
PY
}

echo "Running API smoke test against: $BASE_URL"
echo "Test account: $EMAIL"

# Register and auth
register_response="$(http_json POST "$BASE_URL/api/auth/register" "" "{\"email\":\"$EMAIL\",\"password\":\"$PASSWORD\",\"accepted_legal_terms\":true,\"legal_terms_version\":\"$LEGAL_TERMS_VERSION\",\"legal_privacy_version\":\"$LEGAL_PRIVACY_VERSION\"}")"
token="$(extract_json "$register_response" "access_token")"
echo "Registered user"

me_response="$(http_json GET "$BASE_URL/api/auth/me" "$token")"
me_email="$(extract_json "$me_response" "email")"
if [[ "$me_email" != "$EMAIL" ]]; then
  echo "ERROR: /api/auth/me email mismatch ($me_email != $EMAIL)" >&2
  exit 1
fi
echo "Verified /api/auth/me"

# Recording flow
create_recording_response="$(http_json POST "$BASE_URL/api/recordings" "$token" '{"title":"API Smoke Recording","type":"note","language":"en"}')"
recording_id="$(extract_json "$create_recording_response" "id")"
echo "Created recording: $recording_id"

list_recordings_response="$(http_json GET "$BASE_URL/api/recordings" "$token")"
recordings_count="$(python3 - <<'PY' "$list_recordings_response"
import json,sys
print(len(json.loads(sys.argv[1])))
PY
)"
if [[ "$recordings_count" -lt 1 ]]; then
  echo "ERROR: /api/recordings returned empty list after create" >&2
  exit 1
fi
echo "Verified list recordings"

get_recording_response="$(http_json GET "$BASE_URL/api/recordings/$recording_id" "$token")"
get_recording_id="$(extract_json "$get_recording_response" "id")"
if [[ "$get_recording_id" != "$recording_id" ]]; then
  echo "ERROR: /api/recordings/{id} mismatch" >&2
  exit 1
fi
echo "Verified get recording"

# Agent control-plane + self-host contract
capabilities_response="$(http_json GET "$BASE_URL/api/agents/capabilities" "$token")"
python3 - <<'PY' "$capabilities_response"
import json, sys

body = json.loads(sys.argv[1])
ids = {capability["id"] for capability in body["capabilities"]}
required = {"wai.search", "wai.action.propose", "local.desktop.open", "local.shell"}
missing = sorted(required - ids)
if body.get("schema_version") != "2026-06-03" or missing:
    raise SystemExit(f"bad agent capabilities contract: missing={missing} body={body}")
shell = next(capability for capability in body["capabilities"] if capability["id"] == "local.shell")
if shell.get("availability") != "planned" or shell.get("cloud_supported") is not False:
    raise SystemExit("local.shell must stay planned/cloud-disabled in smoke")
PY
echo "Verified agent capabilities contract"

self_host_contract_response="$(http_json GET "$BASE_URL/api/self-host/migration/contract" "$token")"
python3 - <<'PY' "$self_host_contract_response"
import json, sys

body = json.loads(sys.argv[1])
if body.get("archive_format") != "wai-self-host-export-v1":
    raise SystemExit(f"bad self-host archive format: {body}")
tables = {
    table["table"]: table
    for table in body.get("owned_exportable", {}).get("tables", [])
}
if tables.get("agents", {}).get("classification") != "owned_exportable":
    raise SystemExit("agents table must be owned_exportable in self-host contract")
if tables.get("agent_steps", {}).get("derived_owner_edge", {}).get("parent_table") != "agent_runs":
    raise SystemExit("agent_steps must declare derived owner edge through agent_runs")
PY
echo "Verified self-host migration contract"

create_agent_response="$(http_json POST "$BASE_URL/api/agents" "$token" '{"name":"API Smoke Agent","kind":"smoke","trigger_type":"manual","autonomy":"propose","config":{"steps":[{"tool":"note","args":{"text":"smoke note"}}]}}')"
agent_id="$(extract_json "$create_agent_response" "id")"
echo "Created agent: $agent_id"

agent_run_response="$(http_json POST "$BASE_URL/api/agents/$agent_id/runs" "$token" '{"trigger_payload":{"objective":"smoke run"},"run_inline":true}')"
agent_run_id="$(extract_json "$agent_run_response" "id")"
agent_run_status="$(extract_json "$agent_run_response" "status")"
if [[ "$agent_run_status" != "done" ]]; then
  echo "ERROR: inline agent run did not finish ($agent_run_status)" >&2
  exit 1
fi

agent_steps_response="$(http_json GET "$BASE_URL/api/agents/$agent_id/runs/$agent_run_id/steps" "$token")"
python3 - <<'PY' "$agent_steps_response"
import json, sys

body = json.loads(sys.argv[1])
kinds = [step["kind"] for step in body["steps"]]
expected = ["plan", "tool_call", "tool_result", "verify", "final"]
if kinds != expected:
    raise SystemExit(f"unexpected agent journal: {kinds}")
PY
echo "Verified inline agent run journal"

delete_agent_status="$(curl -sS -o /dev/null -w '%{http_code}' -X DELETE "$BASE_URL/api/agents/$agent_id" -H "Authorization: Bearer $token")"
if [[ "$delete_agent_status" != "204" ]]; then
  echo "ERROR: agent delete failed ($delete_agent_status)" >&2
  exit 1
fi
echo "Verified agent cleanup"

# Summary generation should fail without transcript segments
summary_status="$(curl -sS -o /tmp/waic_summary_out.json -w '%{http_code}' -X POST "$BASE_URL/api/recordings/$recording_id/generate-summary" -H "Authorization: Bearer $token")"
if [[ "$summary_status" != "400" ]]; then
  echo "ERROR: expected 400 from generate-summary without segments, got $summary_status" >&2
  cat /tmp/waic_summary_out.json >&2
  exit 1
fi
echo "Verified generate-summary edge case"

# Entity CRUD
create_entity_response="$(http_json POST "$BASE_URL/api/entities" "$token" '{"type":"person","name":"Smoke Tester","metadata":{"source":"smoke"}}')"
entity_id="$(extract_json "$create_entity_response" "id")"
echo "Created entity: $entity_id"

get_entity_response="$(http_json GET "$BASE_URL/api/entities/$entity_id" "$token")"
entity_name="$(extract_json "$get_entity_response" "name")"
if [[ "$entity_name" != "Smoke Tester" ]]; then
  echo "ERROR: entity fetch mismatch" >&2
  exit 1
fi
echo "Verified entity get"

entity_delete_status="$(curl -sS -o /dev/null -w '%{http_code}' -X DELETE "$BASE_URL/api/entities/$entity_id" -H "Authorization: Bearer $token")"
if [[ "$entity_delete_status" != "204" ]]; then
  echo "ERROR: entity delete failed ($entity_delete_status)" >&2
  exit 1
fi
echo "Verified entity delete"

# Password rotation
change_password_response="$(http_json POST "$BASE_URL/api/settings/change-password" "$token" "{\"current_password\":\"$PASSWORD\",\"new_password\":\"$NEW_PASSWORD\"}")"
change_message="$(extract_json "$change_password_response" "message")"
if [[ -z "$change_message" ]]; then
  echo "ERROR: empty message from change-password" >&2
  exit 1
fi
echo "Verified password change"

old_login_status="$(curl -sS -o /dev/null -w '%{http_code}' -X POST "$BASE_URL/api/auth/login" -H 'Content-Type: application/json' -d "{\"email\":\"$EMAIL\",\"password\":\"$PASSWORD\"}")"
if [[ "$old_login_status" != "401" ]]; then
  echo "ERROR: old password still accepted ($old_login_status)" >&2
  exit 1
fi

new_login_status="$(curl -sS -o /dev/null -w '%{http_code}' -X POST "$BASE_URL/api/auth/login" -H 'Content-Type: application/json' -d "{\"email\":\"$EMAIL\",\"password\":\"$NEW_PASSWORD\"}")"
if [[ "$new_login_status" != "200" ]]; then
  echo "ERROR: new password rejected ($new_login_status)" >&2
  exit 1
fi
echo "Verified new password login"

# Cleanup recording
delete_recording_status="$(curl -sS -o /dev/null -w '%{http_code}' -X DELETE "$BASE_URL/api/recordings/$recording_id" -H "Authorization: Bearer $token")"
if [[ "$delete_recording_status" != "204" ]]; then
  echo "ERROR: recording delete failed ($delete_recording_status)" >&2
  exit 1
fi
echo "Verified recording cleanup"

echo "Smoke run completed successfully"
