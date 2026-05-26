#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 2 || $# -gt 3 ]]; then
  echo "Usage: $0 <sentry-project> <release> [environment]" >&2
  exit 64
fi

PROJECT=$1
RELEASE=$2
ENVIRONMENT=${3:-production}
ORG=${SENTRY_ORG:-waiwai-diy}

if [[ -z "${SENTRY_AUTH_TOKEN:-}" ]]; then
  echo "ERROR: SENTRY_AUTH_TOKEN is required to create Sentry releases and deploy markers." >&2
  exit 1
fi

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
SENTRY_CLI="$SCRIPT_DIR/sentry-cli.sh"

"$SENTRY_CLI" releases new "$RELEASE" --org "$ORG" --project "$PROJECT"

if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  "$SENTRY_CLI" releases set-commits "$RELEASE" --org "$ORG" --project "$PROJECT" --auto --ignore-missing
else
  echo "Sentry commit association skipped for $RELEASE: .git is not available in this build context." >&2
fi

"$SENTRY_CLI" releases finalize "$RELEASE" --org "$ORG" --project "$PROJECT"
"$SENTRY_CLI" releases deploys "$RELEASE" new --org "$ORG" --project "$PROJECT" --env "$ENVIRONMENT"
