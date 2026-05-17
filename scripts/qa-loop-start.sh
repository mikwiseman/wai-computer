#!/usr/bin/env bash
# Start the continuous QA loop in a detached process.
# Prefers tmux; falls back to nohup.
#
# Usage:
#   ./scripts/qa-loop-start.sh
#   DURATION_HOURS=10 DEPLOY_CMD="./scripts/deploy-server.sh" VPS_USER=... ./scripts/qa-loop-start.sh

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_ID="${RUN_ID:-loop_$(date +%Y%m%d_%H%M%S)}"
RUN_DIR="$ROOT_DIR/artifacts/qa-loop/$RUN_ID"
SESSION_NAME="${SESSION_NAME:-qa-loop-$RUN_ID}"
USE_TMUX="${USE_TMUX:-1}"
RUNTIME_ENV_FILE="$RUN_DIR/runtime-env.sh"

mkdir -p "$RUN_DIR"

LOOP_ENV=(
  "RUN_ID=$RUN_ID"
  "DURATION_HOURS=${DURATION_HOURS:-8}"
  "MAX_ITERATIONS=${MAX_ITERATIONS:-0}"
  "STRICT_GATE=${STRICT_GATE:-1}"
  "SLEEP_ON_FAIL_SECONDS=${SLEEP_ON_FAIL_SECONDS:-120}"
  "SLEEP_ON_SUCCESS_SECONDS=${SLEEP_ON_SUCCESS_SECONDS:-30}"
  "BASE_URL=${BASE_URL:-https://wai.computer}"
  "DEPLOY_ON_GREEN=${DEPLOY_ON_GREEN:-1}"
  "DEPLOY_CMD=${DEPLOY_CMD:-}"
  "REQUIRE_DEPLOY_CMD=${REQUIRE_DEPLOY_CMD:-0}"
  "NATIVE_REQUIRED=${NATIVE_REQUIRED:-0}"
  "NATIVE_CMD=${NATIVE_CMD:-}"
  "JWT_SECRET=${JWT_SECRET:-test-secret}"
  "TEST_DATABASE_URL=${TEST_DATABASE_URL:-postgresql+asyncpg://${USER}@localhost:5432/waicomputer_test}"
  "DATABASE_URL=${DATABASE_URL:-}"
)

{
  echo "run_id=$RUN_ID"
  echo "session_name=$SESSION_NAME"
  echo "started_at=$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
  printf "%s\n" "${LOOP_ENV[@]}"
} > "$RUN_DIR/launcher.env"

{
  echo "#!/usr/bin/env bash"
  echo "set -euo pipefail"
  for kv in "${LOOP_ENV[@]}"; do
    key="${kv%%=*}"
    value="${kv#*=}"
    printf "export %s=%q\n" "$key" "$value"
  done
} > "$RUNTIME_ENV_FILE"
chmod +x "$RUNTIME_ENV_FILE"

ln -sfn "$RUN_DIR" "$ROOT_DIR/artifacts/qa-loop/latest"

if [[ "$USE_TMUX" == "1" ]] && command -v tmux >/dev/null 2>&1; then
  tmux new-session -d -s "$SESSION_NAME" \
    "cd '$ROOT_DIR' && bash -lc 'source \"$RUNTIME_ENV_FILE\" && ./scripts/qa-loop.sh | tee \"$RUN_DIR/runner.out\"'"
  echo "Started in tmux session: $SESSION_NAME"
  echo "Attach: tmux attach -t $SESSION_NAME"
  echo "Logs:   tail -f '$RUN_DIR/runner.out'"
else
  nohup bash -lc "cd '$ROOT_DIR' && source '$RUNTIME_ENV_FILE' && ./scripts/qa-loop.sh" > "$RUN_DIR/runner.out" 2>&1 &
  PID=$!
  echo "$PID" > "$RUN_DIR/pid"
  echo "Started with nohup pid=$PID"
  echo "Logs: tail -f '$RUN_DIR/runner.out'"
fi

echo "Run directory: $RUN_DIR"
