#!/usr/bin/env bash
# Continuous QA loop runner (8+ hours by default).
# Runs iterative gates: backend tests, shared tests, remote smoke, optional native, optional deploy.
#
# Usage:
#   ./scripts/qa-loop.sh
#
# Common environment variables:
#   DURATION_HOURS=8
#   BASE_URL=https://api.wai.computer
#   STRICT_GATE=1
#   SLEEP_ON_FAIL_SECONDS=180
#   SLEEP_ON_SUCCESS_SECONDS=30
#   DEPLOY_ON_GREEN=1
#   DEPLOY_CMD="./scripts/deploy-api.sh"
#   REQUIRE_DEPLOY_CMD=0
#   NATIVE_REQUIRED=0
#   NATIVE_CMD="xcodebuild ... && xcodebuild ..."
#   ARTIFACT_ROOT=artifacts/qa-loop
#   JWT_SECRET=test-secret
#   TEST_DATABASE_URL=postgresql+asyncpg://$USER@localhost:5432/waisay_test

set -uo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_ID="${RUN_ID:-$(date +%Y%m%d_%H%M%S)}"
ARTIFACT_BASE="${ARTIFACT_ROOT:-$ROOT_DIR/artifacts/qa-loop}"
RUN_DIR="${ARTIFACT_BASE}/${RUN_ID}"

DURATION_HOURS="${DURATION_HOURS:-8}"
MAX_ITERATIONS="${MAX_ITERATIONS:-0}"
SLEEP_ON_FAIL_SECONDS="${SLEEP_ON_FAIL_SECONDS:-180}"
SLEEP_ON_SUCCESS_SECONDS="${SLEEP_ON_SUCCESS_SECONDS:-30}"
STRICT_GATE="${STRICT_GATE:-1}"

BASE_URL="${BASE_URL:-https://api.wai.computer}"
DEPLOY_ON_GREEN="${DEPLOY_ON_GREEN:-1}"
DEPLOY_CMD="${DEPLOY_CMD:-}"
REQUIRE_DEPLOY_CMD="${REQUIRE_DEPLOY_CMD:-0}"
NATIVE_REQUIRED="${NATIVE_REQUIRED:-0}"
NATIVE_CMD="${NATIVE_CMD:-}"

TEST_DATABASE_URL="${TEST_DATABASE_URL:-postgresql+asyncpg://${USER}@localhost:5432/waisay_test}"
DATABASE_URL="${DATABASE_URL:-$TEST_DATABASE_URL}"
JWT_SECRET="${JWT_SECRET:-test-secret}"

mkdir -p "$RUN_DIR"

LEDGER_FILE="${RUN_DIR}/ledger.csv"
SUMMARY_FILE="${RUN_DIR}/summary.txt"
STATUS_FILE="${RUN_DIR}/status.txt"

if [[ ! -f "$LEDGER_FILE" ]]; then
  echo "timestamp,iteration,phase,backend,shared,remote,native,deploy,gate,duration_seconds,notes" > "$LEDGER_FILE"
fi

timestamp_utc() {
  date -u +"%Y-%m-%dT%H:%M:%SZ"
}

phase_for_elapsed_seconds() {
  local elapsed="$1"
  # 0-2h P0, 2-4.5h P1, 4.5-6.5h P2, 6.5h+ P0 reset/restart
  if (( elapsed < 7200 )); then
    echo "P0_STABILIZE"
  elif (( elapsed < 16200 )); then
    echo "P1_FEATURES"
  elif (( elapsed < 23400 )); then
    echo "P2_EDGES"
  else
    echo "P0_RESET"
  fi
}

native_project_present() {
  find "$ROOT_DIR/ios" "$ROOT_DIR/macos" -name "*.xcodeproj" -print -quit | grep -q . || [[ -x "$ROOT_DIR/android/gradlew" ]]
}

run_step() {
  local name="$1"
  local logfile="$2"
  shift 2

  local start_ts end_ts code
  start_ts="$(date +%s)"
  "$@" >"$logfile" 2>&1
  code=$?
  end_ts="$(date +%s)"
  echo "$name exit=$code duration=$((end_ts - start_ts))s" >> "$logfile"
  return "$code"
}

run_backend_tests() {
  local logfile="$1"
  run_step "backend_tests" "$logfile" bash -lc "
    set -euo pipefail
    cd '$ROOT_DIR/backend'
    source .venv/bin/activate
    JWT_SECRET='$JWT_SECRET' \
    DATABASE_URL='$DATABASE_URL' \
    TEST_DATABASE_URL='$TEST_DATABASE_URL' \
    pytest -q
  "
}

run_shared_tests() {
  local logfile="$1"
  run_step "shared_tests" "$logfile" bash -lc "
    set -euo pipefail
    cd '$ROOT_DIR/shared/WaiSayKit'
    swift test -q
  "
}

run_remote_smoke() {
  local logfile="$1"
  run_step "remote_smoke" "$logfile" bash -lc "
    set -euo pipefail
    cd '$ROOT_DIR'
    BASE_URL='$BASE_URL' ./scripts/api-smoke.sh
  "
}

run_native_tests() {
  local logfile="$1"

  if [[ -n "$NATIVE_CMD" ]]; then
    run_step "native_tests" "$logfile" bash -lc "
      set -euo pipefail
      cd '$ROOT_DIR'
      $NATIVE_CMD
    "
    return $?
  fi

  if ! command -v xcodebuild >/dev/null 2>&1 && [[ ! -x "$ROOT_DIR/android/gradlew" ]]; then
    return 99
  fi

  run_step "native_tests" "$logfile" bash -lc "
    set -euo pipefail
    cd '$ROOT_DIR'
    if command -v xcodebuild >/dev/null 2>&1; then
      if [[ -d '$ROOT_DIR/macos/WaiSay/WaiSay.xcodeproj' ]]; then
        xcodebuild \
          -project '$ROOT_DIR/macos/WaiSay/WaiSay.xcodeproj' \
          -scheme WaiSay \
          -destination 'platform=macOS' \
          CODE_SIGNING_ALLOWED=NO \
          build
      fi
      if [[ -d '$ROOT_DIR/ios/WaiSay/WaiSayiOS.xcodeproj' ]]; then
        xcodebuild \
          -project '$ROOT_DIR/ios/WaiSay/WaiSayiOS.xcodeproj' \
          -scheme WaiSay \
          -destination 'generic/platform=iOS Simulator' \
          CODE_SIGNING_ALLOWED=NO \
          build
      fi
    fi
    if [[ -x '$ROOT_DIR/android/gradlew' ]]; then
      cd '$ROOT_DIR/android'
      ./gradlew --no-daemon testDebugUnitTest assembleDebug
    fi
  "
}

run_deploy() {
  local logfile="$1"

  if [[ -z "$DEPLOY_CMD" ]]; then
    return 99
  fi

  run_step "deploy" "$logfile" bash -lc "
    set -euo pipefail
    cd '$ROOT_DIR'
    $DEPLOY_CMD
  "
}

start_epoch="$(date +%s)"
deadline_epoch="$((start_epoch + (DURATION_HOURS * 3600)))"
iteration=0
green_iterations=0

cat > "$SUMMARY_FILE" <<EOF
run_id=$RUN_ID
started_at=$(timestamp_utc)
duration_hours=$DURATION_HOURS
base_url=$BASE_URL
strict_gate=$STRICT_GATE
deploy_on_green=$DEPLOY_ON_GREEN
native_required=$NATIVE_REQUIRED
EOF

echo "Starting QA loop run: $RUN_ID"
echo "Artifacts: $RUN_DIR"
echo "Will run until: $(date -u -r "$deadline_epoch" +"%Y-%m-%dT%H:%M:%SZ" 2>/dev/null || date -u -d "@$deadline_epoch" +"%Y-%m-%dT%H:%M:%SZ")"

while (( "$(date +%s)" < deadline_epoch )); do
  if [[ "$MAX_ITERATIONS" -gt 0 && "$iteration" -ge "$MAX_ITERATIONS" ]]; then
    break
  fi

  iteration="$((iteration + 1))"
  now_epoch="$(date +%s)"
  elapsed="$((now_epoch - start_epoch))"
  phase="$(phase_for_elapsed_seconds "$elapsed")"
  iter_dir="$RUN_DIR/iteration-$(printf "%04d" "$iteration")"
  mkdir -p "$iter_dir"

  echo "iteration=$iteration phase=$phase started_at=$(timestamp_utc)" | tee "$iter_dir/meta.txt" > /dev/null

  backend_status="FAIL"
  shared_status="FAIL"
  remote_status="FAIL"
  native_status="BLOCKED"
  deploy_status="SKIP"
  gate_status="FAIL"
  notes=""

  if run_backend_tests "$iter_dir/backend.log"; then
    backend_status="PASS"
  else
    backend_status="FAIL"
  fi

  if run_shared_tests "$iter_dir/shared.log"; then
    shared_status="PASS"
  else
    shared_status="FAIL"
  fi

  if run_remote_smoke "$iter_dir/remote-smoke.log"; then
    remote_status="PASS"
  else
    remote_status="FAIL"
  fi

  if native_project_present; then
    if run_native_tests "$iter_dir/native.log"; then
      native_status="PASS"
    else
      rc=$?
      if [[ "$rc" -eq 99 ]]; then
        native_status="SKIP_NO_CMD"
      else
        native_status="FAIL"
      fi
    fi
  else
    native_status="BLOCKED_NO_XCODEPROJ"
  fi

  gate_ok=1
  if [[ "$backend_status" != "PASS" || "$shared_status" != "PASS" || "$remote_status" != "PASS" ]]; then
    gate_ok=0
  fi
  if [[ "$NATIVE_REQUIRED" == "1" && "$native_status" != "PASS" ]]; then
    gate_ok=0
  fi

  if (( gate_ok == 1 )) && [[ "$DEPLOY_ON_GREEN" == "1" ]] && [[ "$phase" != "P2_EDGES" ]]; then
    if run_deploy "$iter_dir/deploy.log"; then
      deploy_status="PASS"
      if run_remote_smoke "$iter_dir/remote-smoke-post-deploy.log"; then
        remote_status="PASS"
      else
        remote_status="FAIL_POST_DEPLOY"
        gate_ok=0
      fi
    else
      rc=$?
      if [[ "$rc" -eq 99 ]]; then
        deploy_status="SKIP_NO_CMD"
        if [[ "$REQUIRE_DEPLOY_CMD" == "1" ]]; then
          gate_ok=0
        fi
      else
        deploy_status="FAIL"
        gate_ok=0
      fi
    fi
  fi

  if (( gate_ok == 1 )); then
    gate_status="PASS"
    green_iterations="$((green_iterations + 1))"
  else
    gate_status="FAIL"
  fi

  end_epoch="$(date +%s)"
  iter_duration="$((end_epoch - now_epoch))"

  if [[ "$native_status" == "BLOCKED_NO_XCODEPROJ" ]]; then
    notes="native_project_missing"
  fi
  if [[ "$deploy_status" == "SKIP_NO_CMD" && "$notes" == "" ]]; then
    notes="deploy_cmd_missing"
  fi

  echo "$(timestamp_utc),$iteration,$phase,$backend_status,$shared_status,$remote_status,$native_status,$deploy_status,$gate_status,$iter_duration,$notes" >> "$LEDGER_FILE"

  {
    echo "timestamp=$(timestamp_utc)"
    echo "iteration=$iteration"
    echo "phase=$phase"
    echo "backend=$backend_status"
    echo "shared=$shared_status"
    echo "remote=$remote_status"
    echo "native=$native_status"
    echo "deploy=$deploy_status"
    echo "gate=$gate_status"
    echo "green_iterations=$green_iterations"
    echo "duration_seconds=$iter_duration"
  } > "$STATUS_FILE"

  echo "iteration=$iteration phase=$phase gate=$gate_status backend=$backend_status shared=$shared_status remote=$remote_status native=$native_status deploy=$deploy_status"

  if [[ "$STRICT_GATE" == "1" && "$gate_status" != "PASS" ]]; then
    sleep "$SLEEP_ON_FAIL_SECONDS"
  else
    sleep "$SLEEP_ON_SUCCESS_SECONDS"
  fi
done

{
  echo "completed_at=$(timestamp_utc)"
  echo "iterations=$iteration"
  echo "green_iterations=$green_iterations"
  echo "ledger=$LEDGER_FILE"
} >> "$SUMMARY_FILE"

echo "QA loop complete for run_id=$RUN_ID"
echo "Summary: $SUMMARY_FILE"
