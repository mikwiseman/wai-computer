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
  "set -euo pipefail;
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
     docker compose ps >&2 || true;
     eval \"\$failure_log_command\" >&2 || true;
     exit 1;
   };
   cd '${REMOTE_ROOT}';
   if git rev-parse --is-inside-work-tree >/dev/null 2>&1 && git remote get-url origin >/dev/null 2>&1; then
     git pull --ff-only origin main;
   else
     echo 'Skipping git pull (no origin remote configured).';
   fi;
   cd backend;
   docker compose build api web celery-worker;
   docker compose up -d api web celery-worker caddy;
   wait_for_service \
     'API health check' \
     'docker compose exec -T api curl -fsS http://localhost:8000/health' \
     24 \
     5 \
     'docker logs --tail 200 waicomputer-api';
   wait_for_service \
     'Web health check' \
     'docker compose exec -T web node -e \"fetch(\\\"http://localhost:3000/login\\\").then(r => process.exit(r.ok ? 0 : 1)).catch(() => process.exit(1))\"' \
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
