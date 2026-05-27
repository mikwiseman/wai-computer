#!/usr/bin/env bash
# Save the Deepgram API key to 1Password without putting the secret in shell
# history, command arguments, or a temporary file.

set -euo pipefail

VAULT="${OP_VAULT:-Development}"
ITEM_TITLE="${OP_ITEM_TITLE:-Deepgram}"
FIELD_LABEL="${OP_FIELD_LABEL:-credential}"

if ! command -v op >/dev/null 2>&1; then
  echo "ERROR: 1Password CLI (op) is required" >&2
  exit 1
fi

read -r -s -p "New Deepgram API key: " DEEPGRAM_API_KEY
echo

if [[ -z "${DEEPGRAM_API_KEY}" ]]; then
  echo "ERROR: key cannot be empty" >&2
  exit 1
fi

update_item_json() {
  DEEPGRAM_API_KEY="${DEEPGRAM_API_KEY}" \
  OP_ITEM_TITLE="${ITEM_TITLE}" \
  OP_FIELD_LABEL="${FIELD_LABEL}" \
  python3 -c '
import json
import os
import sys

item = json.load(sys.stdin)
key = os.environ["DEEPGRAM_API_KEY"]
title = os.environ["OP_ITEM_TITLE"]
field_label = os.environ["OP_FIELD_LABEL"]

item["title"] = title

fields = item.setdefault("fields", [])

def set_field(label, value, field_type="STRING"):
    for field in fields:
        if field.get("id") == label or field.get("label") == label:
            field["label"] = label
            field["type"] = field_type
            field["value"] = value
            return
    fields.append({"id": label, "type": field_type, "label": label, "value": value})

set_field(field_label, key, "CONCEALED")
set_field("username", "Deepgram")
set_field("hostname", "api.deepgram.com")
set_field("type", "API key", "MENU")
set_field(
    "notesPlain",
    "Runtime key for WaiComputer Deepgram Nova-3 realtime transcription.",
)

json.dump(item, sys.stdout)
'
}

if op item get "${ITEM_TITLE}" --vault "${VAULT}" --format json >/dev/null 2>&1; then
  op item get "${ITEM_TITLE}" --vault "${VAULT}" --format json \
    | update_item_json \
    | op item edit "${ITEM_TITLE}" --vault "${VAULT}" >/dev/null
else
  op item template get "API Credential" \
    | update_item_json \
    | op item create --vault "${VAULT}" - >/dev/null
fi

echo "Saved Deepgram key to op://${VAULT}/${ITEM_TITLE}/${FIELD_LABEL}"
