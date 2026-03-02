#!/usr/bin/env bash
# Show status for the latest or specified QA loop run.
#
# Usage:
#   ./scripts/qa-loop-status.sh
#   ./scripts/qa-loop-status.sh loop_20260225_225225

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BASE_DIR="$ROOT_DIR/artifacts/qa-loop"
RUN_ID="${1:-}"

if [[ -z "$RUN_ID" ]]; then
  if [[ -L "$BASE_DIR/latest" ]]; then
    RUN_DIR="$(readlink "$BASE_DIR/latest")"
    RUN_ID="$(basename "$RUN_DIR")"
  else
    RUN_ID="$(ls -1t "$BASE_DIR" 2>/dev/null | head -n 1 || true)"
    RUN_DIR="$BASE_DIR/$RUN_ID"
  fi
else
  RUN_DIR="$BASE_DIR/$RUN_ID"
fi

if [[ -z "$RUN_ID" || ! -d "$RUN_DIR" ]]; then
  echo "No QA run directory found." >&2
  exit 1
fi

echo "run_id=$RUN_ID"
echo "run_dir=$RUN_DIR"
echo

if [[ -f "$RUN_DIR/status.txt" ]]; then
  echo "--- status.txt ---"
  cat "$RUN_DIR/status.txt"
  echo
fi

if [[ -f "$RUN_DIR/summary.txt" ]]; then
  echo "--- summary.txt ---"
  cat "$RUN_DIR/summary.txt"
  echo
fi

if [[ -f "$RUN_DIR/ledger.csv" ]]; then
  echo "--- ledger tail ---"
  tail -n 10 "$RUN_DIR/ledger.csv"
  echo
fi

if [[ -f "$RUN_DIR/runner.out" ]]; then
  echo "--- runner.out tail ---"
  tail -n 30 "$RUN_DIR/runner.out"
fi
