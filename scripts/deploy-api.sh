#!/usr/bin/env bash
# Deploy API + web services to VPS.
# Usage:
#   VPS_USER=<release-user> ./scripts/deploy-api.sh
# Optional:
#   VPS_HOST=<release-host>
#   SSH_KEY_PATH=~/.ssh/id_ed25519
#   REMOTE_ROOT=/opt/waisay

set -euo pipefail

VPS_HOST="${VPS_HOST:-<release-host>}"
VPS_USER="${VPS_USER:-}"
SSH_KEY_PATH="${SSH_KEY_PATH:-$HOME/.ssh/id_ed25519}"
REMOTE_ROOT="${REMOTE_ROOT:-/opt/waisay}"
REMOTE_ENV_FILE="${REMOTE_ENV_FILE:-/etc/waisay/backend.env}"

if [[ -z "$VPS_USER" ]]; then
  echo "ERROR: VPS_USER is required" >&2
  exit 1
fi

if [[ ! -f "$SSH_KEY_PATH" ]]; then
  echo "ERROR: SSH key not found at $SSH_KEY_PATH" >&2
  exit 1
fi

echo "Deploying API + web to ${VPS_USER}@${VPS_HOST} ..."

ssh \
  -i "$SSH_KEY_PATH" \
  -o BatchMode=yes \
  -o StrictHostKeyChecking=accept-new \
  "${VPS_USER}@${VPS_HOST}" \
  "install -d -m 755 '${REMOTE_ROOT}'"

rsync \
  -az \
  --delete \
  --exclude '.git/' \
  --exclude '.github/' \
  --exclude 'backend/.env' \
  --exclude 'backend/.venv/' \
  --exclude 'backend/htmlcov/' \
  --exclude 'backend/coverage.xml' \
  --exclude 'web/node_modules/' \
  --exclude 'web/.next/' \
  --exclude 'android/.gradle/' \
  --exclude 'backups/' \
  --exclude 'releases/' \
  -e "ssh -i ${SSH_KEY_PATH} -o BatchMode=yes -o StrictHostKeyChecking=accept-new" \
  ./ \
  "${VPS_USER}@${VPS_HOST}:${REMOTE_ROOT}/"

ssh \
  -i "$SSH_KEY_PATH" \
  -o BatchMode=yes \
  -o StrictHostKeyChecking=accept-new \
  "${VPS_USER}@${VPS_HOST}" \
  "set -euo pipefail;
   PROD_ROOT='${REMOTE_ROOT}';
   PROD_ENV_FILE='${REMOTE_ENV_FILE}';
   wait_for_service() {
     local name=\"\$1\";
     local command=\"\$2\";
     local attempts=\"\$3\";
     local delay=\"\$4\";
     local failure_log_command=\"\$5\";
     local attempt;
     for attempt in \$(seq 1 \"\$attempts\"); do
       if eval \"\$command\" >/dev/null 2>&1; then
         return 0;
       fi;
       sleep \"\$delay\";
     done;
     echo \"\$name did not become healthy after \$((attempts * delay)) seconds.\" >&2;
     docker_compose ps >&2 || true;
     eval \"\$failure_log_command\" >&2 || true;
     exit 1;
   };
   require_env_key() {
     local key=\"\$1\";
     if ! grep -Eq \"^\${key}=.+\" \"\$PROD_ENV_FILE\"; then
       echo \"ERROR: \$PROD_ENV_FILE is missing required key \$key\" >&2;
       exit 1;
     fi;
   };
   docker_compose() {
     docker compose --env-file \"\$PROD_ENV_FILE\" \"\$@\";
   };
   install -d -m 755 \"\$PROD_ROOT\";
   install -d -m 755 \"\$PROD_ROOT/releases/macos\";
   if [[ ! -f \"\$PROD_ENV_FILE\" ]]; then
     echo \"ERROR: Missing production env file at \$PROD_ENV_FILE\" >&2;
     echo \"Provision it first or run CI bootstrap deploy.\" >&2;
     exit 1;
   fi;
   chmod 600 \"\$PROD_ENV_FILE\";
   chown root:root \"\$PROD_ENV_FILE\";
   ln -sfn \"\$PROD_ENV_FILE\" \"\$PROD_ROOT/backend/.env\";
   require_env_key POSTGRES_USER;
   require_env_key POSTGRES_PASSWORD;
   require_env_key POSTGRES_DB;
   require_env_key JWT_SECRET;
   require_env_key FRONTEND_URL;
   require_env_key CORS_ORIGINS;
   require_env_key ELEVENLABS_API_KEY;
   require_env_key AUTH_COOKIE_DOMAIN;
   cd \"\$PROD_ROOT/backend\";
   export WAISAY_ENV_FILE=\"\$PROD_ENV_FILE\";
   docker_compose config >/dev/null;
   docker_compose build api web celery-worker;
   docker_compose up -d api web celery-worker caddy;
   wait_for_service \
     'API health check' \
     'docker_compose exec -T api curl -fsS http://localhost:8000/health' \
     24 \
     5 \
     'docker logs --tail 200 waisay-api';
   wait_for_service \
     'Web health check' \
     'docker_compose exec -T web node -e \"fetch(\\\"http://localhost:3000/login\\\").then(r => process.exit(r.ok ? 0 : 1)).catch(() => process.exit(1))\"' \
     24 \
     5 \
     'docker logs --tail 200 waisay-web';
   wait_for_service \
     'Celery worker health check' \
     '[[ \"\$(docker inspect --format '\''{{if .State.Health}}{{.State.Health.Status}}{{else}}unknown{{end}}'\'' waisay-celery-worker 2>/dev/null)\" == healthy ]]' \
     24 \
     5 \
     'docker logs --tail 200 waisay-celery-worker';
   echo 'Remote deploy + health checks successful.'"

echo "Deployment completed."
