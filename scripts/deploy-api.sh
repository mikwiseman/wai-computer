#!/usr/bin/env bash
# Sync source to the VPS and build API + web services on the server.
# Usage:
#   VPS_USER=root ./scripts/deploy-api.sh
# Optional:
#   VPS_HOST=157.180.47.68
#   SSH_KEY_PATH=~/.ssh/id_ed25519
#   REMOTE_ROOT=/opt/waicomputer

set -euo pipefail

VPS_HOST="${VPS_HOST:-157.180.47.68}"
VPS_USER="${VPS_USER:-}"
SSH_KEY_PATH="${SSH_KEY_PATH:-$HOME/.ssh/id_ed25519}"
REMOTE_ROOT="${REMOTE_ROOT:-/opt/waicomputer}"
REMOTE_ENV_FILE="${REMOTE_ENV_FILE:-/etc/waicomputer/backend.env}"
GIT_SHA="${GIT_SHA:-$(git rev-parse HEAD)}"
GIT_DIRTY="${GIT_DIRTY:-false}"
if [[ -n "$(git status --porcelain)" ]]; then
  GIT_DIRTY=true
fi
ALLOW_DIRTY_DEPLOY="${ALLOW_DIRTY_DEPLOY:-0}"

if [[ -z "$VPS_USER" ]]; then
  echo "ERROR: VPS_USER is required" >&2
  exit 1
fi

if [[ ! -f "$SSH_KEY_PATH" ]]; then
  echo "ERROR: SSH key not found at $SSH_KEY_PATH" >&2
  exit 1
fi

if [[ -z "${SENTRY_AUTH_TOKEN:-}" ]]; then
  echo "ERROR: SENTRY_AUTH_TOKEN is required to create Sentry release and deploy markers." >&2
  exit 1
fi

if [[ "$GIT_DIRTY" == "true" && "$ALLOW_DIRTY_DEPLOY" != "1" ]]; then
  echo "ERROR: refusing to deploy a dirty worktree. Commit first or set ALLOW_DIRTY_DEPLOY=1 for an explicit emergency deploy." >&2
  git status --short >&2
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
  --exclude '.claude/' \
  --exclude '.playwright-mcp/' \
  --exclude '.env' \
  --exclude '.env.*' \
  --exclude '.venv/' \
  --exclude '.venv312/' \
  --exclude '.pytest_cache/' \
  --exclude '.ruff_cache/' \
  --exclude '.coverage' \
  --exclude '__pycache__/' \
  --exclude 'backend/.env' \
  --exclude 'backend/.env.*' \
  --exclude 'backend/.venv/' \
  --exclude 'backend/.venv312/' \
  --exclude 'backend/.pytest_cache/' \
  --exclude 'backend/.ruff_cache/' \
  --exclude 'backend/htmlcov/' \
  --exclude 'backend/coverage.xml' \
  --exclude 'web/node_modules/' \
  --exclude 'web/.env' \
  --exclude 'web/.env.*' \
  --exclude 'web/.next/' \
  --exclude 'web/coverage/' \
  --exclude 'web/test-results/' \
  --exclude 'web/tsconfig.tsbuildinfo' \
  --exclude 'android/.gradle/' \
  --exclude 'android/build/' \
  --exclude 'android/app/build/' \
  --exclude 'artifacts/' \
  --exclude 'desktop/**/bin/' \
  --exclude 'desktop/**/obj/' \
  --exclude 'linux/**/bin/' \
  --exclude 'linux/**/obj/' \
  --exclude 'macos/WaiComputer/build/' \
  --exclude 'shared/WaiComputerKit/.build/' \
  --exclude 'scripts/nightly/.venv/' \
  --exclude 'scripts/nightly/.artifacts/' \
  --exclude 'windows/**/bin/' \
  --exclude 'windows/**/obj/' \
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

SENTRY_ORG=${SENTRY_ORG:-waiwai-diy} scripts/sentry-release.sh "waicomputer-backend" "waicomputer-backend@${GIT_SHA}" production
SENTRY_ORG=${SENTRY_ORG:-waiwai-diy} scripts/sentry-release.sh "waicomputer-web" "waicomputer-web@${GIT_SHA}" production

echo "Deployment completed."
