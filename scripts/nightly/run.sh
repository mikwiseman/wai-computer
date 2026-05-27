#!/usr/bin/env bash
# WaiComputer nightly realtime dictation QA harness.
# See scripts/nightly/README.md.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
NIGHTLY_DIR="$ROOT_DIR/scripts/nightly"
VENV_DIR="$NIGHTLY_DIR/.venv"

cd "$ROOT_DIR"

if [[ ! -d "$VENV_DIR" ]]; then
  python3 -m venv "$VENV_DIR"
fi
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"

# Idempotent install: only if the network deps are missing.
python -c 'import httpx, websockets' 2>/dev/null || pip install --quiet --disable-pip-version-check 'httpx>=0.26' 'websockets>=13'

LOG_FILE="$NIGHTLY_DIR/.artifacts/last-run.log"
JSON_REPORT="$NIGHTLY_DIR/.artifacts/last-report.json"
MD_REPORT="$NIGHTLY_DIR/.artifacts/last-report.md"
mkdir -p "$NIGHTLY_DIR/.artifacts"

echo "==> OpenAI realtime dictation production path"
if python "$ROOT_DIR/scripts/evaluate-realtime-dictation.py" --output "$JSON_REPORT" 2>&1 | tee "$LOG_FILE"; then
  echo "==> OpenAI realtime PASS"
  rc=0
else
  rc=$?
  echo "==> OpenAI realtime FAIL (exit=$rc)"
fi

if [[ -f "$JSON_REPORT" ]]; then
  python - "$JSON_REPORT" "$MD_REPORT" <<'PY'
import json
import sys
from pathlib import Path

source = Path(sys.argv[1])
target = Path(sys.argv[2])
payload = json.loads(source.read_text(encoding="utf-8"))
lines = [
    "# WaiComputer realtime dictation QA",
    "",
    f"- Generated: `{payload.get('generated_at', '-')}`",
    f"- Base URL: `{payload.get('base_url', '-')}`",
    f"- Fixture seconds: `{payload.get('fixture_seconds', '-')}`",
    "",
    "| Mode | Provider | Model | OK | First text p50 | Final p50 | WER p50 |",
    "| --- | --- | --- | ---: | ---: | ---: | ---: |",
]
for row in payload.get("summary", []):
    lines.append(
        "| {mode} | {provider} | `{model}` | {ok_runs}/{runs} | {first} ms | {final} ms | {wer} |".format(
            mode=row.get("mode", "-"),
            provider=row.get("provider", "-"),
            model=row.get("model", "-"),
            ok_runs=row.get("ok_runs", 0),
            runs=row.get("runs", 0),
            first=row.get("median_first_text_ms"),
            final=row.get("median_final_ms"),
            wer=row.get("median_wer"),
        )
    )
target.write_text("\n".join(lines) + "\n", encoding="utf-8")
PY
fi

echo "==> Report: $MD_REPORT"
exit "$rc"
