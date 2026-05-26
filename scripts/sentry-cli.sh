#!/usr/bin/env bash
set -euo pipefail

SENTRY_CLI_NPM_VERSION=${SENTRY_CLI_NPM_VERSION:-3.4.3}

if command -v sentry-cli >/dev/null 2>&1; then
  exec sentry-cli "$@"
fi

if command -v npx >/dev/null 2>&1; then
  exec npx -y "@sentry/cli@${SENTRY_CLI_NPM_VERSION}" "$@"
fi

echo "ERROR: sentry-cli or npx is required for Sentry release artifact uploads." >&2
exit 1
