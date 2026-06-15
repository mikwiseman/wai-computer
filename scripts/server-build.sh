#!/usr/bin/env bash
# Restart WaiComputer production services on the VPS using prebuilt images.
#
# This script is intended to run on the production server after source has been
# synced to /opt/waicomputer. Production deploys should load images before this
# script runs; server-side builds require ALLOW_SERVER_SIDE_BUILD=1.
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
DEPLOY_HEALTH_WAIT_TIMEOUT_SECONDS="${DEPLOY_HEALTH_WAIT_TIMEOUT_SECONDS:-240}"
MIN_FREE_DISK_MB="${MIN_FREE_DISK_MB:-4096}"
ALLOW_SERVER_SIDE_BUILD="${ALLOW_SERVER_SIDE_BUILD:-0}"

if [[ -z "$GIT_SHA" ]]; then
  echo "ERROR: GIT_SHA is required for production builds" >&2
  exit 1
fi
WAICOMPUTER_BACKEND_IMAGE="${WAICOMPUTER_BACKEND_IMAGE:-waicomputer-backend:${GIT_SHA}}"
WAICOMPUTER_WEB_IMAGE="${WAICOMPUTER_WEB_IMAGE:-waicomputer-web:${GIT_SHA}}"
DEPLOY_SERVICES=(telegram-bot-api api web celery-worker caddy)
export GIT_SHA GIT_DIRTY WAICOMPUTER_BACKEND_IMAGE WAICOMPUTER_WEB_IMAGE

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

require_image() {
  local image="$1"
  if ! docker image inspect "$image" >/dev/null 2>&1; then
    echo "ERROR: required deploy image is not loaded: $image" >&2
    echo "Build and load images before running this script, or set ALLOW_SERVER_SIDE_BUILD=1 explicitly." >&2
    exit 1
  fi
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

if [[ "$ALLOW_SERVER_SIDE_BUILD" == "1" ]]; then
  echo "WARNING: Server-side image builds are enabled for this deploy." >&2
  # Build ONE service at a time with Celery stopped. The 3.8 GB VPS OOMs when
  # building all images concurrently (BuildKit parallelism); stopping the worker
  # first frees ~1 GB of headroom for the heavy web (Next.js) build. Celery's
  # queue must already be drained before a deploy.
  docker_compose stop celery-worker
  CELERY_STOPPED_FOR_BUILD=true
  docker_compose_timeout build api
  docker_compose_timeout build web
elif [[ "$ALLOW_SERVER_SIDE_BUILD" == "0" ]]; then
  echo "Server-side image builds are disabled; using preloaded deploy images."
  require_image "$WAICOMPUTER_BACKEND_IMAGE"
  require_image "$WAICOMPUTER_WEB_IMAGE"
else
  echo "ERROR: ALLOW_SERVER_SIDE_BUILD must be 0 or 1" >&2
  exit 1
fi

# Apply DB migrations with the freshly built image before swapping containers
# in. Migrations are additive, so the still-running old API tolerates the new
# schema during the brief window until `up -d` recreates the containers.
docker_compose_timeout run --rm --no-deps --pull never api alembic upgrade head

docker_compose up \
  -d \
  --remove-orphans \
  --no-build \
  --pull never \
  --wait \
  --wait-timeout "$DEPLOY_HEALTH_WAIT_TIMEOUT_SECONDS" \
  "${DEPLOY_SERVICES[@]}"
CELERY_STOPPED_FOR_BUILD=false

wait_for_service \
  "Telegram Bot API service" \
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

echo "Configuring Telegram webhook through the active Bot API endpoint..."
docker_compose exec -T api python - < "$PROD_ROOT/scripts/configure-telegram-webhook.py"

echo "Server build and deploy successful."
