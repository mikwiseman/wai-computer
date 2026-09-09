#!/usr/bin/env bash
set -euo pipefail
DEPLOY_SHA=${1:?Commit SHA required}
[[ "$DEPLOY_SHA" =~ ^[0-9a-f]{40}$ ]] || exit 64
exec 9>/var/lock/waicomputer-deploy.lock
flock -n 9
DEPLOY_STAGE="/opt/waicomputer-web-releases/$DEPLOY_SHA"
DEPLOY_IMAGE="waicomputer-web:$DEPLOY_SHA"
CANDIDATE="waicomputer-web-candidate-${DEPLOY_SHA:0:12}"
PROD_ENV=/etc/waicomputer/backend.env
OLD_IMAGE=$(docker inspect waicomputer-web --format '{{.Config.Image}}')
OLD_SERVICES=$(docker ps --format '{{.Names}} {{.ID}}' | grep -v '^waicomputer-web ' | sort)
ENV_SHA=$(sha256sum "$PROD_ENV" | cut -d' ' -f1)
SWAPPED=0
VERIFIED=0
cd /opt/waicomputer/backend
compose_web() {
  WAICOMPUTER_WEB_IMAGE="$1" docker compose --env-file "$PROD_ENV" up -d --no-deps --no-build --pull never --wait --wait-timeout 90 web
}
cleanup() {
  docker rm -f "$CANDIDATE" >/dev/null 2>&1 || true
  if [[ "$SWAPPED" == 1 && "$VERIFIED" == 0 ]]; then
    echo 'Web verification failed; restoring the previous image.' >&2
    compose_web "$OLD_IMAGE"
  fi
}
trap cleanup EXIT
docker image inspect "$DEPLOY_IMAGE" >/dev/null
docker run -d --name "$CANDIDATE" --network backend_web --memory 512m \
  -p 127.0.0.1::3000 -e API_BASE_URL=http://api:8000 -e NEXT_PUBLIC_API_BASE_URL= \
  "$DEPLOY_IMAGE" >/dev/null
CANDIDATE_PORT=$(docker port "$CANDIDATE" 3000/tcp | cut -d: -f2)
for attempt in $(seq 1 30); do
  if curl -fsS "http://127.0.0.1:$CANDIDATE_PORT/" >/dev/null; then break; fi
  sleep 1
done
python3 "$DEPLOY_STAGE/web/scripts/school-smoke.py" "http://127.0.0.1:$CANDIDATE_PORT"
docker rm -f "$CANDIDATE" >/dev/null
printf '%s\n' "$OLD_IMAGE" > "$DEPLOY_STAGE/previous-image.txt"
SWAPPED=1
compose_web "$DEPLOY_IMAGE"
python3 "$DEPLOY_STAGE/web/scripts/school-smoke.py" https://wai.computer
curl -fsS --resolve wai.computer:443:157.180.47.68 https://wai.computer/ -o "$DEPLOY_STAGE/origin-homepage.html"
grep -q 'WaiWai, LLC' "$DEPLOY_STAGE/origin-homepage.html"
curl -fsS https://wai.computer/health >/dev/null
test "$OLD_SERVICES" = "$(docker ps --format '{{.Names}} {{.ID}}' | grep -v '^waicomputer-web ' | sort)"
test "$ENV_SHA" = "$(sha256sum "$PROD_ENV" | cut -d' ' -f1)"
# Keep the deployed public source available to the next full deployment.
rsync -a --delete --exclude=node_modules --exclude=.next "$DEPLOY_STAGE/web/" /opt/waicomputer/web/
VERIFIED=1
echo "Verified web release $DEPLOY_SHA; other containers and runtime env unchanged."
