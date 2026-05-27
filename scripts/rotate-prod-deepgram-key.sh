#!/usr/bin/env bash
# Rotate the production Deepgram API key in the root-owned runtime env file on
# the VPS without echoing the key.

set -euo pipefail

VPS_HOST="${VPS_HOST:-<release-host>}"
VPS_USER="${VPS_USER:-}"
SSH_KEY_PATH="${SSH_KEY_PATH:-$HOME/.ssh/id_ed25519}"
REMOTE_ENV_FILE="${REMOTE_ENV_FILE:-<remote-env-file>}"

if [[ -z "${VPS_USER}" ]]; then
  echo "ERROR: VPS_USER is required" >&2
  exit 1
fi

if [[ ! -f "${SSH_KEY_PATH}" ]]; then
  echo "ERROR: SSH key not found at ${SSH_KEY_PATH}" >&2
  exit 1
fi

read -r -s -p "New DEEPGRAM_API_KEY: " DEEPGRAM_API_KEY
echo

if [[ -z "${DEEPGRAM_API_KEY}" ]]; then
  echo "ERROR: key cannot be empty" >&2
  exit 1
fi

export DEEPGRAM_API_KEY
if ! ssh \
  -i "${SSH_KEY_PATH}" \
  -o BatchMode=yes \
  -o StrictHostKeyChecking=accept-new \
  "${VPS_USER}@${VPS_HOST}" \
  "test -f '${REMOTE_ENV_FILE}'"; then
  echo "ERROR: ${REMOTE_ENV_FILE} does not exist on ${VPS_HOST}" >&2
  echo "Bootstrap the full runtime env file first, then rotate the key." >&2
  exit 1
fi

ssh \
  -i "${SSH_KEY_PATH}" \
  -o BatchMode=yes \
  -o StrictHostKeyChecking=accept-new \
  "${VPS_USER}@${VPS_HOST}" \
  "cat '${REMOTE_ENV_FILE}' 2>/dev/null || true" \
  | python3 -c '
import os
import sys

key = os.environ["DEEPGRAM_API_KEY"]
lines = sys.stdin.read().splitlines()

updated = False
for index, line in enumerate(lines):
    if line.startswith("DEEPGRAM_API_KEY="):
        lines[index] = f"DEEPGRAM_API_KEY={key}"
        updated = True
        break

if not updated:
    lines.append(f"DEEPGRAM_API_KEY={key}")

content = "\n".join(lines).rstrip("\n") + "\n"
print(content, end="")
' \
  | ssh \
      -i "${SSH_KEY_PATH}" \
      -o BatchMode=yes \
      -o StrictHostKeyChecking=accept-new \
      "${VPS_USER}@${VPS_HOST}" \
      "set -euo pipefail;
       install -d -m 700 \"$(dirname "${REMOTE_ENV_FILE}")\";
       tmp=\$(mktemp);
       cat >\"\$tmp\";
       install -m 600 -o root -g root \"\$tmp\" \"${REMOTE_ENV_FILE}\";
       rm -f \"\$tmp\";
       grep -Eq '^DEEPGRAM_API_KEY=.+' \"${REMOTE_ENV_FILE}\""

echo "Rotated DEEPGRAM_API_KEY in ${VPS_HOST}:${REMOTE_ENV_FILE}"
