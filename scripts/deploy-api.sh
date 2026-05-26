#!/usr/bin/env bash
# Sync source to the VPS and build API + web services on the server.
# Usage:
#   VPS_USER=<release-user> ./scripts/deploy-api.sh
# Optional:
#   VPS_HOST=<release-host>
#   SSH_KEY_PATH=~/.ssh/id_ed25519
#   REMOTE_ROOT=<remote-root>

set -euo pipefail

VPS_HOST="${VPS_HOST:-<release-host>}"
VPS_USER="${VPS_USER:-}"
SSH_KEY_PATH="${SSH_KEY_PATH:-$HOME/.ssh/id_ed25519}"
REMOTE_ROOT="${REMOTE_ROOT:-<remote-root>}"
REMOTE_ENV_FILE="${REMOTE_ENV_FILE:-<remote-env-file>}"
GIT_SHA="${GIT_SHA:-$(git rev-parse HEAD)}"
GIT_DIRTY="${GIT_DIRTY:-false}"
if [[ -n "$(git status --porcelain)" ]]; then
  GIT_DIRTY=true
fi

if [[ -z "$VPS_USER" ]]; then
  echo "ERROR: VPS_USER is required" >&2
  exit 1
fi

if [[ ! -f "$SSH_KEY_PATH" ]]; then
  echo "ERROR: SSH key not found at $SSH_KEY_PATH" >&2
  exit 1
fi

echo "Syncing source to ${VPS_USER}@${VPS_HOST}:${REMOTE_ROOT} ..."

ssh \
  -i "$SSH_KEY_PATH" \
  -o BatchMode=yes \
  -o StrictHostKeyChecking=accept-new \
  "${VPS_USER}@${VPS_HOST}" \
  "install -d -m 755 '${REMOTE_ROOT}'"

rsync \
  -az \
  --delete \
  --no-owner \
  --no-group \
  --exclude '.git/' \
  --exclude '.github/' \
  --exclude '.codex/' \
  --exclude '.venv/' \
  --exclude '.venv312/' \
  --exclude '.pytest_cache/' \
  --exclude '.ruff_cache/' \
  --exclude '.coverage' \
  --exclude '__pycache__/' \
  --exclude 'backend/.env' \
  --exclude 'backend/.venv/' \
  --exclude 'backend/.venv312/' \
  --exclude 'backend/.pytest_cache/' \
  --exclude 'backend/.ruff_cache/' \
  --exclude 'backend/htmlcov/' \
  --exclude 'backend/coverage.xml' \
  --exclude 'web/node_modules/' \
  --exclude 'web/.next/' \
  --exclude 'web/coverage/' \
  --exclude 'web/test-results/' \
  --exclude 'web/tsconfig.tsbuildinfo' \
  --exclude 'android/.gradle/' \
  --exclude 'android/build/' \
  --exclude 'android/app/build/' \
  --exclude 'macos/WaiComputer/build/' \
  --exclude 'shared/WaiComputerKit/.build/' \
  --exclude 'scripts/nightly/.venv/' \
  --exclude 'scripts/nightly/.artifacts/' \
  --exclude 'backups/' \
  --exclude 'releases/' \
  -e "ssh -i ${SSH_KEY_PATH} -o BatchMode=yes -o StrictHostKeyChecking=accept-new" \
  ./ \
  "${VPS_USER}@${VPS_HOST}:${REMOTE_ROOT}/"

echo "Building and restarting services on ${VPS_USER}@${VPS_HOST} ..."

ssh \
  -i "$SSH_KEY_PATH" \
  -o BatchMode=yes \
  -o StrictHostKeyChecking=accept-new \
  "${VPS_USER}@${VPS_HOST}" \
  "PROD_ROOT='${REMOTE_ROOT}' PROD_ENV_FILE='${REMOTE_ENV_FILE}' GIT_SHA='${GIT_SHA}' GIT_DIRTY='${GIT_DIRTY}' bash '${REMOTE_ROOT}/scripts/server-build.sh'"

echo "Deployment completed."
