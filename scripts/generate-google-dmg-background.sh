#!/usr/bin/env bash
set -euo pipefail

OUTPUT_PATH=${1:?"usage: generate-google-dmg-background.sh <output-path> [prompt-file]"}
PROMPT_FILE=${2:-}
: "${GOOGLE_API_KEY:?Set GOOGLE_API_KEY in the environment before running this script.}"

mkdir -p "$(dirname "$OUTPUT_PATH")"

python3 - "$OUTPUT_PATH" "$PROMPT_FILE" <<'PY'
import base64
import json
import os
import sys
import urllib.request
from pathlib import Path

output_path = Path(sys.argv[1])
prompt_file = Path(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[2] else None
api_key = os.environ["GOOGLE_API_KEY"]
model = os.environ.get("GOOGLE_IMAGE_MODEL", "gemini-2.5-flash-image")

prompt = """
Create a premium, minimal macOS installer background for a direct-download productivity app DMG.
Canvas: 960x620 landscape.
Style: extremely minimal, elegant, quiet, premium, modern, no clutter.
Composition: dark charcoal matte background with a very subtle vertical gradient, soft low-contrast teal glow on the left and muted warm sand glow on the right, large negative space in the center, faint abstract geometry only.
Important constraints: no text, no letters, no logos, no app icons, no screenshots, no devices, no windows, no arrows, no people, no objects, no photoreal scenes, no border frame, no perspective room.
The image must leave clear space for a drag-and-drop installer layout with one app icon on the left and Applications folder on the right.
Keep it more minimalistic than a typical marketing graphic.
""".strip()

if prompt_file and prompt_file.exists():
    prompt = prompt_file.read_text().strip()

payload = {
    "contents": [{"parts": [{"text": prompt}]}],
    "generationConfig": {
        "responseModalities": ["TEXT", "IMAGE"]
    }
}

req = urllib.request.Request(
    f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
    data=json.dumps(payload).encode("utf-8"),
    headers={
        "Content-Type": "application/json",
        "x-goog-api-key": api_key,
    },
    method="POST",
)

with urllib.request.urlopen(req, timeout=120) as resp:
    data = json.load(resp)

for candidate in data.get("candidates", []):
    for part in candidate.get("content", {}).get("parts", []):
        inline_data = part.get("inlineData") or part.get("inline_data")
        if not inline_data:
            continue
        mime = inline_data.get("mimeType") or inline_data.get("mime_type") or ""
        raw = inline_data.get("data")
        if raw and mime.startswith("image/"):
            output_path.write_bytes(base64.b64decode(raw))
            print(output_path)
            raise SystemExit(0)

raise SystemExit(f"No image returned by Google API. Response keys: {list(data.keys())}")
PY
