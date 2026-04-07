#!/bin/bash
#
# eval.sh — WaiSay single-metric evaluation
#
# Runs ALL test suites (backend pytest, frontend vitest, Swift tests)
# and outputs a single integer: total failures across all suites.
#
# 0 = all tests pass. Target: 0.
#
set -uo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
FAILURES=0

# ─── Backend (pytest) ───────────────────────────────────────────
backend_failures() {
  cd "$PROJECT_ROOT/backend"
  source .venv312/bin/activate

  local output
  output=$(pytest -q --no-cov --tb=no 2>&1)
  local exit_code=$?

  if [ "$exit_code" -eq 0 ]; then
    echo 0
    return
  fi

  # pytest summary line: "X failed, Y passed, Z error" — count both failed and error
  local failed errors total
  failed=$(echo "$output" | grep -oE '[0-9]+ failed' | grep -oE '[0-9]+' || echo "0")
  errors=$(echo "$output" | grep -oE '[0-9]+ error' | grep -oE '[0-9]+' || echo "0")
  total=$(( ${failed:-0} + ${errors:-0} ))
  if [ "$total" -gt 0 ]; then
    echo "$total"
  else
    # Non-zero exit but no parseable count — treat as 1 failure
    echo 1
  fi
}

# ─── Frontend (vitest) ──────────────────────────────────────────
frontend_failures() {
  cd "$PROJECT_ROOT/web"

  local output
  output=$(pnpm vitest run --reporter=verbose 2>&1)
  local exit_code=$?

  if [ "$exit_code" -eq 0 ]; then
    echo 0
    return
  fi

  # vitest summary: "Tests  X failed | Y passed"
  local failed
  failed=$(echo "$output" | grep -oE 'Tests[[:space:]]+[0-9]+ failed' | grep -oE '[0-9]+' || echo "")
  if [ -n "$failed" ]; then
    echo "$failed"
  else
    # Non-zero exit but no parseable count
    echo 1
  fi
}

# ─── Swift (WaiSayKit) ─────────────────────────────────────
swift_failures() {
  cd "$PROJECT_ROOT/shared/WaiSayKit"

  local output
  output=$(swift test 2>&1)
  local exit_code=$?

  if [ "$exit_code" -eq 0 ]; then
    echo 0
    return
  fi

  # Swift test output: "Executed N tests, with X failures"
  local failed
  failed=$(echo "$output" | grep -oE 'with [0-9]+ failure' | grep -oE '[0-9]+' || echo "")
  if [ -n "$failed" ]; then
    echo "$failed"
  else
    # Build error or other non-zero exit
    echo 1
  fi
}

# ─── Run all suites ─────────────────────────────────────────────

BACKEND=$(backend_failures 2>/dev/null)
FAILURES=$((FAILURES + ${BACKEND:-0}))

FRONTEND=$(frontend_failures 2>/dev/null)
FAILURES=$((FAILURES + ${FRONTEND:-0}))

SWIFT=$(swift_failures 2>/dev/null)
FAILURES=$((FAILURES + ${SWIFT:-0}))

# Output the single metric
echo "$FAILURES"
