#!/usr/bin/env bash
# WaiSay nightly QA harness — entry point for hourly cron iteration.
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

# Idempotent install: only if websockets is missing.
python -c 'import websockets' 2>/dev/null || pip install --quiet --disable-pip-version-check 'websockets>=13'

# Sanity check key file exists before any network call.
if [[ ! -f "$HOME/.config/waisay/inworld.env" ]]; then
  echo "ERROR: $HOME/.config/waisay/inworld.env missing." >&2
  echo "Fetch with: ssh root@157.180.47.68 'grep ^INWORLD_API_KEY= /etc/waisay/backend.env' > $HOME/.config/waisay/inworld.env && chmod 600 $HOME/.config/waisay/inworld.env" >&2
  exit 2
fi

LOG_FILE="$NIGHTLY_DIR/.artifacts/last-run.log"
mkdir -p "$NIGHTLY_DIR/.artifacts"

echo "==> Tier 1 (Inworld TTS+STT round trip)"
if python "$NIGHTLY_DIR/runner.py" 2>&1 | tee "$LOG_FILE"; then
  echo "==> Tier 1 PASS"
  rc=0
else
  rc=$?
  echo "==> Tier 1 FAIL (exit=$rc)"
fi

if [[ "${NIGHTLY_TIER2:-0}" == "1" ]]; then
  echo "==> Tier 2 (real macOS app) — not yet implemented in this iteration"
fi

echo "==> Report: $NIGHTLY_DIR/.artifacts/last-report.md"
exit "$rc"
