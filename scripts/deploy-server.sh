#!/usr/bin/env bash
# Preferred production deploy entrypoint. Kept separate from deploy-api.sh so
# callers can use a name that matches the current server-build deployment model.
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
exec "$SCRIPT_DIR/deploy-api.sh" "$@"
