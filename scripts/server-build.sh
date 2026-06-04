#!/usr/bin/env bash
# Build and restart WaiComputer production services on the release server.
#
# This script is intended to run on the production server after source has been
# synced to the private deploy root. It keeps all Docker image builds on the
# server and uses the private production runtime env file.
set -euo pipefail

DEPLOY_LOCK_FILE="${DEPLOY_LOCK_FILE:-/var/lock/waicomputer-deploy.lock}"
if [[ "${WAICOMPUTER_DEPLOY_LOCK_HELD:-0}" != "1" ]]; then
  exec flock -n "$DEPLOY_LOCK_FILE" env WAICOMPUTER_DEPLOY_LOCK_HELD=1 bash "$0" "$@"
fi

PROD_ROOT="${PROD_ROOT:-}"
PROD_ENV_FILE="${PROD_ENV_FILE:-}"
PROD_ENV_DIR=$(dirname "$PROD_ENV_FILE")
LEGACY_ENV_FILE=""
GIT_SHA="${GIT_SHA:-}"
GIT_DIRTY="${GIT_DIRTY:-false}"
DEPLOY_BUILD_TIMEOUT_SECONDS="${DEPLOY_BUILD_TIMEOUT_SECONDS:-1800}"
MIN_FREE_DISK_MB="${MIN_FREE_DISK_MB:-4096}"

if [[ -z "$GIT_SHA" ]]; then
  echo "ERROR: GIT_SHA is required for production builds" >&2
  exit 1
fi
if [[ -z "$PROD_ROOT" ]]; then
  echo "ERROR: PROD_ROOT is required for production builds" >&2
  exit 1
fi
if [[ -z "$PROD_ENV_FILE" ]]; then
  echo "ERROR: PROD_ENV_FILE is required for production builds" >&2
  exit 1
fi
export GIT_SHA GIT_DIRTY

wait_for_service() {
  local name="$1"
  local command="$2"
  local attempts="$3"
  local delay="$4"
  local failure_log_command="$5"
  local attempt

  for attempt in $(seq 1 "$attempts"); do
    if eval "$command" >/dev/null 2>&1; then
      return 0
    fi
    sleep "$delay"
  done

  echo "$name did not become healthy after $((attempts * delay)) seconds." >&2
  docker_compose ps >&2 || true
  eval "$failure_log_command" >&2 || true
  exit 1
}

require_env_key() {
  local key="$1"
  if ! grep -Eq "^${key}=.+" "$PROD_ENV_FILE"; then
    echo "ERROR: $PROD_ENV_FILE is missing required key $key" >&2
    exit 1
  fi
}

read_env_key() {
  local key="$1"
  awk -F= -v key="$key" '$1 == key { value = substr($0, length(key) + 2) } END { print value }' "$PROD_ENV_FILE" \
    | sed -e 's/^"//' -e 's/"$//' -e "s/^'//" -e "s/'$//"
}

docker_compose() {
  docker compose --env-file "$PROD_ENV_FILE" "$@"
}

docker_compose_timeout() {
  timeout "$DEPLOY_BUILD_TIMEOUT_SECONDS" docker compose --env-file "$PROD_ENV_FILE" "$@"
}

require_disk_headroom() {
  local available_mb
  available_mb="$(df -Pm "$PROD_ROOT" | awk 'NR == 2 {print $4}')"
  if [[ -z "$available_mb" || "$available_mb" -lt "$MIN_FREE_DISK_MB" ]]; then
    echo "ERROR: insufficient disk headroom on $PROD_ROOT (${available_mb:-unknown} MB available; need ${MIN_FREE_DISK_MB} MB)." >&2
    exit 1
  fi
}

legacy_db_container=$(docker ps -aq --filter label=com.docker.compose.project=backend --filter label=com.docker.compose.service=db | head -n 1 || true)
if [[ -n "$legacy_db_container" ]]; then
  LEGACY_ENV_FILE=$(docker inspect -f '{{ index .Config.Labels "com.docker.compose.project.environment_file" }}' "$legacy_db_container" 2>/dev/null || true)
fi

install -d -m 755 "$PROD_ROOT"
install -d -m 755 "$PROD_ROOT/releases/macos"
install -d -m 700 "$PROD_ENV_DIR"

if [[ ! -f "$PROD_ENV_FILE" && -n "$LEGACY_ENV_FILE" && -f "$LEGACY_ENV_FILE" ]]; then
  install -m 600 -o root -g root "$LEGACY_ENV_FILE" "$PROD_ENV_FILE"
  sed -i 's|^FRONTEND_URL=.*|FRONTEND_URL=https://wai.computer|' "$PROD_ENV_FILE"
  sed -i 's|^AUTH_COOKIE_DOMAIN=.*|AUTH_COOKIE_DOMAIN=wai.computer|' "$PROD_ENV_FILE"
  sed -i 's|^CORS_ORIGINS=.*|CORS_ORIGINS=["https://wai.computer"]|' "$PROD_ENV_FILE"
  sed -i 's|^EMAIL_FROM=.*<|EMAIL_FROM=WaiComputer <|' "$PROD_ENV_FILE"
  grep -q '^FRONTEND_URL=' "$PROD_ENV_FILE" || printf '%s\n' 'FRONTEND_URL=https://wai.computer' >> "$PROD_ENV_FILE"
  grep -q '^AUTH_COOKIE_DOMAIN=' "$PROD_ENV_FILE" || printf '%s\n' 'AUTH_COOKIE_DOMAIN=wai.computer' >> "$PROD_ENV_FILE"
  grep -q '^CORS_ORIGINS=' "$PROD_ENV_FILE" || printf '%s\n' 'CORS_ORIGINS=["https://wai.computer"]' >> "$PROD_ENV_FILE"
elif [[ ! -f "$PROD_ENV_FILE" ]]; then
  echo "ERROR: Missing production env file at $PROD_ENV_FILE" >&2
  echo "Provision it first or copy the current production env into place." >&2
  exit 1
fi

chmod 600 "$PROD_ENV_FILE"
chown root:root "$PROD_ENV_FILE"
ln -sfn "$PROD_ENV_FILE" "$PROD_ROOT/backend/.env"

require_env_key POSTGRES_USER
require_env_key POSTGRES_PASSWORD
require_env_key POSTGRES_DB
require_env_key JWT_SECRET
require_env_key FRONTEND_URL
require_env_key CORS_ORIGINS
require_env_key DEEPGRAM_API_KEY
require_env_key ELEVENLABS_API_KEY
require_env_key AUTH_COOKIE_DOMAIN
require_env_key SENTRY_DSN
require_env_key SENTRY_AUTH_TOKEN
require_env_key TELEGRAM_API_ID
require_env_key TELEGRAM_API_HASH

cd "$PROD_ROOT/backend"
export WAICOMPUTER_ENV_FILE="$PROD_ENV_FILE"
export SENTRY_AUTH_TOKEN
SENTRY_AUTH_TOKEN=$(read_env_key SENTRY_AUTH_TOKEN)
export SENTRY_UPLOAD_REQUIRED=1

CELERY_STOPPED_FOR_BUILD=false
restart_celery_on_exit() {
  if [[ "$CELERY_STOPPED_FOR_BUILD" == "true" ]]; then
    echo "Restarting celery-worker after interrupted deploy..."
    docker_compose up -d celery-worker || true
  fi
}
trap restart_celery_on_exit EXIT

docker_compose config >/dev/null
require_disk_headroom

# Build ONE service at a time with Celery stopped. The 3.8 GB VPS OOMs when
# building all images concurrently (BuildKit parallelism); stopping the worker
# first frees ~1 GB of headroom for the heavy web (Next.js) build. Celery's
# queue must already be drained before a deploy.
docker_compose stop celery-worker
CELERY_STOPPED_FOR_BUILD=true
docker_compose_timeout build api
docker_compose_timeout build celery-worker
docker_compose_timeout build web

# Apply DB migrations with the freshly built image before swapping containers
# in. Migrations are additive, so the still-running old API tolerates the new
# schema during the brief window until `up -d` recreates the containers.
docker_compose_timeout run --rm api alembic upgrade head

docker_compose up -d --remove-orphans telegram-bot-api api web celery-worker caddy
CELERY_STOPPED_FOR_BUILD=false

wait_for_service \
  "Telegram Bot API running" \
  "[[ \"$(docker inspect --format '{{.State.Running}}' waicomputer-telegram-bot-api 2>/dev/null)\" == true ]]" \
  12 \
  2 \
  "docker logs --tail 200 waicomputer-telegram-bot-api"

wait_for_service \
  "API health check" \
  "docker_compose exec -T api curl -fsS http://localhost:8000/health" \
  24 \
  5 \
  "docker logs --tail 200 waicomputer-api"

wait_for_service \
  "Web health check" \
  "docker_compose exec -T web node -e \"fetch('http://localhost:3000/').then(r => process.exit(r.status < 500 ? 0 : 1)).catch(() => process.exit(1))\"" \
  24 \
  5 \
  "docker logs --tail 200 waicomputer-web"

wait_for_service \
  "Celery worker health check" \
  "[[ \"$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}unknown{{end}}' waicomputer-celery-worker 2>/dev/null)\" == healthy ]]" \
  24 \
  5 \
  "docker logs --tail 200 waicomputer-celery-worker"

# Caddy bind-mounts Caddyfile by path. rsync replaces files by rename, giving
# them a new inode; restart Caddy when the mounted file inside the container does
# not match the host file.
host_caddy_sum=$(md5sum "$PROD_ROOT/backend/Caddyfile" | awk '{print $1}')
container_caddy_sum=$(docker exec waicomputer-caddy md5sum /etc/caddy/Caddyfile 2>/dev/null | awk '{print $1}' || echo none)
if [[ "$host_caddy_sum" != "$container_caddy_sum" ]]; then
  echo "Caddyfile changed on host ($host_caddy_sum vs $container_caddy_sum); restarting caddy"
  docker_compose restart caddy
  wait_for_service \
    "Caddy post-restart" \
    "[[ \"$(docker inspect --format '{{.State.Running}}' waicomputer-caddy 2>/dev/null)\" == true ]]" \
    12 \
    2 \
    "docker logs --tail 200 waicomputer-caddy"
  wait_for_service \
    "Caddy HTTP health check" \
    "docker exec waicomputer-caddy wget -qO- --header='Host: wai.computer' --tries=1 --timeout=5 http://localhost/health" \
    18 \
    2 \
    "docker logs --tail 200 waicomputer-caddy"
fi

echo "Server build and deploy successful."
