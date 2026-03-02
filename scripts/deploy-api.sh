#!/usr/bin/env bash
# Deploy API + web services to VPS.
# Usage:
#   VPS_USER=<release-user> ./scripts/deploy-api.sh
# Optional:
#   VPS_HOST=89.167.125.46
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
   cd '${REMOTE_ROOT}';
   if git rev-parse --is-inside-work-tree >/dev/null 2>&1 && git remote get-url origin >/dev/null 2>&1; then
     git pull --ff-only origin main;
   else
     echo 'Skipping git pull (no origin remote configured).';
   fi;
   cd backend;
   docker compose build api web;
   docker compose up -d api web caddy;
   sleep 10;
   docker compose exec -T api curl -fsS http://localhost:8000/health > /dev/null;
   docker compose exec -T web node -e \"fetch('http://localhost:3000/login').then(r => process.exit(r.ok ? 0 : 1)).catch(() => process.exit(1))\";
   echo 'Remote deploy + health checks successful.'"

echo "Deployment completed."
