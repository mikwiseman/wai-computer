#!/usr/bin/env bash
# Build only web locally; validate a candidate, then replace only the web service.
set -euo pipefail
cd "$(dirname "$0")/.."
test -z "$(git status --porcelain)" || { echo 'Commit the worktree before deploying.' >&2; exit 1; }
DEPLOY_SHA=$(git rev-parse HEAD)
DEPLOY_HOST=${VPS_HOST:-root@157.180.47.68}
DEPLOY_IMAGE="waicomputer-web:$DEPLOY_SHA"
DEPLOY_STAGE="/opt/waicomputer-web-releases/$DEPLOY_SHA"
docker info >/dev/null

read_remote_key() {
  ssh -o BatchMode=yes "$DEPLOY_HOST" python3 - "$1" <<'PY'
import sys
from pathlib import Path
for line in Path('/etc/waicomputer/backend.env').read_text().splitlines():
    if line.startswith(sys.argv[1] + '='):
        print(line.split('=', 1)[1].strip().strip('"\x27'))
        break
else:
    raise SystemExit('Missing required deployment configuration: ' + sys.argv[1])
PY
}
export SENTRY_AUTH_TOKEN
SENTRY_AUTH_TOKEN=$(read_remote_key SENTRY_AUTH_TOKEN)
WEB_BUILD_DSN=$(read_remote_key WEB_SENTRY_DSN)
test -n "$SENTRY_AUTH_TOKEN" && test -n "$WEB_BUILD_DSN"

docker buildx build --platform linux/amd64 --file web/Dockerfile \
  --build-arg API_BASE_URL=http://api:8000 --build-arg NEXT_PUBLIC_API_BASE_URL= \
  --build-arg "NEXT_PUBLIC_SENTRY_DSN=$WEB_BUILD_DSN" \
  --build-arg NEXT_PUBLIC_SENTRY_ENVIRONMENT=production \
  --build-arg "SENTRY_RELEASE=waicomputer-web@$DEPLOY_SHA" \
  --build-arg SENTRY_UPLOAD_REQUIRED=1 \
  --secret id=sentry_auth_token,env=SENTRY_AUTH_TOKEN \
  --tag "$DEPLOY_IMAGE" --load .

ssh -o BatchMode=yes "$DEPLOY_HOST" "mkdir -p '$DEPLOY_STAGE'"
git archive HEAD web scripts/deploy-web-server.sh scripts/sentry-release.sh scripts/sentry-cli.sh \
  | ssh -o BatchMode=yes "$DEPLOY_HOST" "tar -x -C '$DEPLOY_STAGE'"
docker save "$DEPLOY_IMAGE" | gzip -1 | ssh -o BatchMode=yes "$DEPLOY_HOST" 'gzip -dc | docker load'
ssh -o BatchMode=yes "$DEPLOY_HOST" "bash '$DEPLOY_STAGE/scripts/deploy-web-server.sh' '$DEPLOY_SHA'"
./scripts/sentry-release.sh waicomputer-web "waicomputer-web@$DEPLOY_SHA" production
unset SENTRY_AUTH_TOKEN
