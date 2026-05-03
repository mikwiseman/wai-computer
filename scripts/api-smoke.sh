#!/usr/bin/env bash
# Basic API smoke test for WaiSay.
# Usage: BASE_URL=https://say.waiwai.is ./scripts/api-smoke.sh

set -euo pipefail

BASE_URL="${BASE_URL:-https://say.waiwai.is}"
RUN_ID="$(date +%s)"
EMAIL_PREFIX="${EMAIL_PREFIX:-qa.smoke}"
EMAIL="${EMAIL_PREFIX}.${RUN_ID}@example.com"
PASSWORD="${PASSWORD:-Passw0rd!234}"
NEW_PASSWORD="${NEW_PASSWORD:-Passw0rd!567}"

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
register_response="$(http_json POST "$BASE_URL/api/auth/register" "" "{\"email\":\"$EMAIL\",\"password\":\"$PASSWORD\"}")"
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
