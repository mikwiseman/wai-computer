#!/usr/bin/env bash
# Build production images locally, load them onto the VPS, then swap services.
# Usage:
#   VPS_USER=root ./scripts/deploy-api.sh
# Optional:
#   VPS_HOST=157.180.47.68
#   SSH_KEY_PATH=~/.ssh/id_ed25519
#   REMOTE_ROOT=/opt/waicomputer
#   DEPLOY_IMAGE_SOURCE=local|server
#   DEPLOY_IMAGE_PLATFORM=linux/amd64

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
DEPLOY_IMAGE_SOURCE="${DEPLOY_IMAGE_SOURCE:-local}"
DEPLOY_IMAGE_PLATFORM="${DEPLOY_IMAGE_PLATFORM:-linux/amd64}"
DEPLOY_BUILD_PULL="${DEPLOY_BUILD_PULL:-1}"
REMOTE_BUILD_CACHE_PRUNE="${REMOTE_BUILD_CACHE_PRUNE:-1}"
WAICOMPUTER_BACKEND_IMAGE="${WAICOMPUTER_BACKEND_IMAGE:-waicomputer-backend:${GIT_SHA}}"
WAICOMPUTER_WEB_IMAGE="${WAICOMPUTER_WEB_IMAGE:-waicomputer-web:${GIT_SHA}}"

ssh_remote() {
  ssh \
    -i "$SSH_KEY_PATH" \
    -o BatchMode=yes \
    -o StrictHostKeyChecking=accept-new \
    "${VPS_USER}@${VPS_HOST}" \
    "$@"
}

require_command() {
  local command_name="$1"
  if ! command -v "$command_name" >/dev/null 2>&1; then
    echo "ERROR: $command_name is required for DEPLOY_IMAGE_SOURCE=local" >&2
    exit 1
  fi
}

fetch_remote_env_key() {
  local key="$1"
  ssh_remote "PROD_ENV_FILE='${REMOTE_ENV_FILE}' KEY='${key}' python3 - <<'PY'
import os
import sys
from pathlib import Path

path = Path(os.environ['PROD_ENV_FILE'])
key = os.environ['KEY']

if not path.exists():
    print(f'ERROR: production env file is missing at {path}', file=sys.stderr)
    sys.exit(1)

for raw_line in path.read_text().splitlines():
    line = raw_line.strip()
    if not line or line.startswith('#') or '=' not in line:
        continue
    name, value = line.split('=', 1)
    if name.strip() != key:
        continue
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'\"', \"'\"}:
        value = value[1:-1]
    if not value:
        print(f'ERROR: {path} has empty required key {key}', file=sys.stderr)
        sys.exit(1)
    print(value)
    sys.exit(0)

print(f'ERROR: {path} is missing required key {key}', file=sys.stderr)
sys.exit(1)
PY"
}

fetch_optional_remote_env_key() {
  local key="$1"
  ssh_remote "PROD_ENV_FILE='${REMOTE_ENV_FILE}' KEY='${key}' python3 - <<'PY'
import os
from pathlib import Path

path = Path(os.environ['PROD_ENV_FILE'])
key = os.environ['KEY']

if not path.exists():
    raise SystemExit(0)

for raw_line in path.read_text().splitlines():
    line = raw_line.strip()
    if not line or line.startswith('#') or '=' not in line:
        continue
    name, value = line.split('=', 1)
    if name.strip() != key:
        continue
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'\"', \"'\"}:
        value = value[1:-1]
    print(value)
    raise SystemExit(0)
PY"
}

build_and_load_images() {
  require_command docker
  require_command gzip

  if ! docker info >/dev/null 2>&1; then
    echo "ERROR: Docker daemon is not available locally; refusing to build on the production VPS." >&2
    echo "Start Docker locally or rerun with DEPLOY_IMAGE_SOURCE=server ALLOW_SERVER_SIDE_BUILD=1." >&2
    exit 1
  fi

  if ! docker buildx version >/dev/null 2>&1; then
    echo "ERROR: docker buildx is required for local production image builds." >&2
    exit 1
  fi

  local web_sentry_dsn
  local web_sentry_environment
  local pull_args=()
  web_sentry_dsn="$(fetch_remote_env_key WEB_SENTRY_DSN)"
  web_sentry_environment="$(fetch_optional_remote_env_key WEB_SENTRY_ENVIRONMENT)"
  web_sentry_environment="${web_sentry_environment:-production}"

  if [[ "$DEPLOY_BUILD_PULL" == "1" ]]; then
    pull_args+=(--pull)
  elif [[ "$DEPLOY_BUILD_PULL" != "0" ]]; then
    echo "ERROR: DEPLOY_BUILD_PULL must be 0 or 1" >&2
    exit 1
  fi

  echo "Building backend image ${WAICOMPUTER_BACKEND_IMAGE} for ${DEPLOY_IMAGE_PLATFORM} ..."
  docker buildx build \
    --platform "$DEPLOY_IMAGE_PLATFORM" \
    "${pull_args[@]}" \
    --build-arg "GIT_SHA=${GIT_SHA}" \
    --build-arg "GIT_DIRTY=${GIT_DIRTY}" \
    --tag "$WAICOMPUTER_BACKEND_IMAGE" \
    --load \
    backend

  echo "Building web image ${WAICOMPUTER_WEB_IMAGE} for ${DEPLOY_IMAGE_PLATFORM} ..."
  docker buildx build \
    --platform "$DEPLOY_IMAGE_PLATFORM" \
    "${pull_args[@]}" \
    --file web/Dockerfile \
    --build-arg "API_BASE_URL=http://api:8000" \
    --build-arg "NEXT_PUBLIC_API_BASE_URL=" \
    --build-arg "NEXT_PUBLIC_SENTRY_DSN=${web_sentry_dsn}" \
    --build-arg "NEXT_PUBLIC_SENTRY_ENVIRONMENT=${web_sentry_environment}" \
    --build-arg "SENTRY_RELEASE=waicomputer-web@${GIT_SHA}" \
    --build-arg "SENTRY_UPLOAD_REQUIRED=1" \
    --secret id=sentry_auth_token,env=SENTRY_AUTH_TOKEN \
    --tag "$WAICOMPUTER_WEB_IMAGE" \
    --load \
    .

  if [[ "$REMOTE_BUILD_CACHE_PRUNE" == "1" ]]; then
    echo "Pruning remote Docker build cache before loading images ..."
    ssh_remote "docker builder prune -af --filter 'until=24h' >/dev/null"
  elif [[ "$REMOTE_BUILD_CACHE_PRUNE" != "0" ]]; then
    echo "ERROR: REMOTE_BUILD_CACHE_PRUNE must be 0 or 1" >&2
    exit 1
  fi

  echo "Loading prebuilt images on ${VPS_USER}@${VPS_HOST} ..."
  docker save "$WAICOMPUTER_BACKEND_IMAGE" "$WAICOMPUTER_WEB_IMAGE" \
    | gzip -1 \
    | ssh_remote "gzip -dc | docker load"
}

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

case "$DEPLOY_IMAGE_SOURCE" in
  local)
    build_and_load_images
    REMOTE_SERVER_BUILD_ENV="ALLOW_SERVER_SIDE_BUILD='0'"
    ;;
  server)
    if [[ "${ALLOW_SERVER_SIDE_BUILD:-0}" != "1" ]]; then
      echo "ERROR: DEPLOY_IMAGE_SOURCE=server requires ALLOW_SERVER_SIDE_BUILD=1." >&2
      echo "Server-side builds share production CPU/RAM/disk and are disabled by default." >&2
      exit 1
    fi
    echo "WARNING: building images on the production VPS because DEPLOY_IMAGE_SOURCE=server was explicitly requested." >&2
    REMOTE_SERVER_BUILD_ENV="ALLOW_SERVER_SIDE_BUILD='1'"
    ;;
  *)
    echo "ERROR: DEPLOY_IMAGE_SOURCE must be local or server" >&2
    exit 1
    ;;
esac

echo "Syncing source to ${VPS_USER}@${VPS_HOST}:${REMOTE_ROOT} ..."

ssh_remote \
  "install -d -m 755 '${REMOTE_ROOT}' && if [ ! -d '${REMOTE_ROOT}/.git' ]; then rm -f '${REMOTE_ROOT}/.git'; fi"

rsync \
  -az \
  --delete \
  --no-owner \
  --no-group \
  --exclude '.git' \
  --exclude '.git/' \
  --exclude '.github/' \
  --exclude '.codex/' \
  --exclude '.claude/' \
  --exclude '.playwright-mcp/' \
  --exclude '.build/' \
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

ssh_remote \
  "${REMOTE_SERVER_BUILD_ENV} PROD_ROOT='${REMOTE_ROOT}' PROD_ENV_FILE='${REMOTE_ENV_FILE}' GIT_SHA='${GIT_SHA}' GIT_DIRTY='${GIT_DIRTY}' WAICOMPUTER_BACKEND_IMAGE='${WAICOMPUTER_BACKEND_IMAGE}' WAICOMPUTER_WEB_IMAGE='${WAICOMPUTER_WEB_IMAGE}' bash '${REMOTE_ROOT}/scripts/server-build.sh'"

SENTRY_ORG=${SENTRY_ORG:-waiwai-diy} scripts/sentry-release.sh "waicomputer-backend" "waicomputer-backend@${GIT_SHA}" production
SENTRY_ORG=${SENTRY_ORG:-waiwai-diy} scripts/sentry-release.sh "waicomputer-web" "waicomputer-web@${GIT_SHA}" production

echo "Deployment completed."
