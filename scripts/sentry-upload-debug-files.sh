#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 2 ]]; then
  echo "Usage: $0 <sentry-project> <path> [path...]" >&2
  exit 64
fi

PROJECT=$1
shift
ORG=${SENTRY_ORG:-waiwai-diy}

if [[ -z "${SENTRY_AUTH_TOKEN:-}" ]]; then
  echo "ERROR: SENTRY_AUTH_TOKEN is required to upload Sentry debug files." >&2
  exit 1
fi

for path in "$@"; do
  if [[ ! -e "$path" ]]; then
    echo "ERROR: Sentry debug file path does not exist: $path" >&2
    exit 1
  fi
done

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
"$SCRIPT_DIR/sentry-cli.sh" debug-files upload --org "$ORG" --project "$PROJECT" --wait "$@"
