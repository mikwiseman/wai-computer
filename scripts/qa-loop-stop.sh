#!/usr/bin/env bash
# Stop a running QA loop started with qa-loop-start.sh.
#
# Usage:
#   ./scripts/qa-loop-stop.sh loop_20260225_225225
#   ./scripts/qa-loop-stop.sh   # stops latest if available

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

SESSION_NAME=""
if [[ -f "$RUN_DIR/launcher.env" ]]; then
  SESSION_NAME="$(grep '^session_name=' "$RUN_DIR/launcher.env" | cut -d= -f2- || true)"
fi

stopped=0
if [[ -n "$SESSION_NAME" ]] && command -v tmux >/dev/null 2>&1; then
  if tmux has-session -t "$SESSION_NAME" 2>/dev/null; then
    tmux kill-session -t "$SESSION_NAME"
    echo "Stopped tmux session: $SESSION_NAME"
    stopped=1
  fi
fi

if [[ "$stopped" -eq 0 && -f "$RUN_DIR/pid" ]]; then
  PID="$(cat "$RUN_DIR/pid")"
  if [[ -n "$PID" ]] && ps -p "$PID" >/dev/null 2>&1; then
    kill "$PID"
    echo "Stopped pid: $PID"
    stopped=1
  fi
fi

if [[ "$stopped" -eq 0 ]]; then
  echo "No active process found for run_id=$RUN_ID"
else
  echo "Stopped run_id=$RUN_ID"
fi
