#!/usr/bin/env bash
# Deploy API + web services to VPS.
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

ssh \
  -i "$SSH_KEY_PATH" \
  -o BatchMode=yes \
  -o StrictHostKeyChecking=accept-new \
  "${VPS_USER}@${VPS_HOST}" \
  "set -euo pipefail;
   PROD_ROOT='${REMOTE_ROOT}';
   PROD_ENV_FILE='${REMOTE_ENV_FILE}';
   PROD_ENV_DIR=\"\$(dirname \"\$PROD_ENV_FILE\")\";
   LEGACY_ENV_FILE='';
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
   legacy_db_container=\"\$(docker ps -aq --filter label=com.docker.compose.project=backend --filter label=com.docker.compose.service=db | head -n 1 || true)\";
   if [[ -n \"\$legacy_db_container\" ]]; then
     LEGACY_ENV_FILE=\"\$(docker inspect -f '{{ index .Config.Labels \"com.docker.compose.project.environment_file\" }}' \"\$legacy_db_container\" 2>/dev/null || true)\";
   fi;
   install -d -m 755 \"\$PROD_ROOT\";
   install -d -m 755 \"\$PROD_ROOT/releases/macos\";
   install -d -m 700 \"\$PROD_ENV_DIR\";
   if [[ ! -f \"\$PROD_ENV_FILE\" && -n \"\$LEGACY_ENV_FILE\" && -f \"\$LEGACY_ENV_FILE\" ]]; then
     install -m 600 -o root -g root \"\$LEGACY_ENV_FILE\" \"\$PROD_ENV_FILE\";
     sed -i 's|^FRONTEND_URL=.*|FRONTEND_URL=https://wai.computer|' \"\$PROD_ENV_FILE\";
     sed -i 's|^AUTH_COOKIE_DOMAIN=.*|AUTH_COOKIE_DOMAIN=wai.computer|' \"\$PROD_ENV_FILE\";
     sed -i 's|^CORS_ORIGINS=.*|CORS_ORIGINS=[\"https://wai.computer\"]|' \"\$PROD_ENV_FILE\";
     sed -i 's|^EMAIL_FROM=.*<|EMAIL_FROM=WaiComputer <|' \"\$PROD_ENV_FILE\";
     grep -q '^FRONTEND_URL=' \"\$PROD_ENV_FILE\" || printf '%s\n' 'FRONTEND_URL=https://wai.computer' >> \"\$PROD_ENV_FILE\";
     grep -q '^AUTH_COOKIE_DOMAIN=' \"\$PROD_ENV_FILE\" || printf '%s\n' 'AUTH_COOKIE_DOMAIN=wai.computer' >> \"\$PROD_ENV_FILE\";
     grep -q '^CORS_ORIGINS=' \"\$PROD_ENV_FILE\" || printf '%s\n' 'CORS_ORIGINS=[\"https://wai.computer\"]' >> \"\$PROD_ENV_FILE\";
   elif [[ ! -f \"\$PROD_ENV_FILE\" ]]; then
     echo \"ERROR: Missing production env file at \$PROD_ENV_FILE\" >&2;
     echo \"Provision it first or copy the current production env into place.\" >&2;
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
   export WAICOMPUTER_ENV_FILE=\"\$PROD_ENV_FILE\";
   docker_compose config >/dev/null;
   docker_compose build api web celery-worker;
   docker_compose up -d --remove-orphans api web celery-worker caddy;
   wait_for_service \
     'API health check' \
     'docker_compose exec -T api curl -fsS http://localhost:8000/health' \
     24 \
     5 \
     'docker logs --tail 200 waicomputer-api';
   wait_for_service \
     'Web health check' \
     'docker_compose exec -T web node -e \"fetch(\\\"http://localhost:3000/login\\\").then(r => process.exit(r.ok ? 0 : 1)).catch(() => process.exit(1))\"' \
     24 \
     5 \
     'docker logs --tail 200 waicomputer-web';
   wait_for_service \
     'Celery worker health check' \
     '[[ \"\$(docker inspect --format '\''{{if .State.Health}}{{.State.Health.Status}}{{else}}unknown{{end}}'\'' waicomputer-celery-worker 2>/dev/null)\" == healthy ]]' \
     24 \
     5 \
     'docker logs --tail 200 waicomputer-celery-worker';
   echo 'Remote deploy + health checks successful.'"

echo "Deployment completed."
