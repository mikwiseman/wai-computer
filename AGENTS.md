# WaiSay

AI second brain for recordings, transcription, search, and summaries.

## Production

- Canonical host: `https://say.waiwai.is`
- API under `/api/*`; health: `GET /health`
- Old `wai.computer` / `api.wai.computer` hosts retired
- Server: `root@157.180.47.68`
- Deploy root: `/opt/waisay`
- Runtime env source of truth: `/etc/waisay/backend.env`
- `/opt/waisay/backend/.env` must be a symlink to `/etc/waisay/backend.env`

Keep aligned in env: `FRONTEND_URL=https://say.waiwai.is`, `AUTH_COOKIE_DOMAIN=say.waiwai.is`, `CORS_ORIGINS` includes `https://say.waiwai.is`, `SENTRY_DSN` points at current project.

## Deploy

- CI deploys on push to `main` when `backend/**`, `web/**`, `shared/**`, `ios/**`, `macos/**`, `android/**`, `scripts/**`, `.github/workflows/deploy.yml`, or `.dockerignore` change.
- Manual: `VPS_USER=root ./scripts/deploy-api.sh`
- Deploy builds `api`, `web`, `celery-worker`, starts `caddy`, checks health for all three.
- Verify GitHub Actions `Deploy` workflow is green after every push.

## Local Dev

```bash
# Backend
cd backend && python -m venv .venv && source .venv/bin/activate
pip install ".[dev]" && docker compose up db -d
alembic upgrade head && uvicorn app.main:app --reload

# Frontend
cd web && pnpm install && pnpm dev

# Full stack
cd backend && docker compose up --build
```

## Tests

```bash
cd backend && pytest -x -q           # unit (80% coverage gate)
cd backend && pytest -m integration --no-cov
cd backend && ruff check .
cd web && pnpm lint && pnpm test:unit && pnpm test:e2e
cd shared/WaiSayKit && swift test -q
```

Native builds:
```bash
xcodebuild -project macos/WaiSay/WaiSay.xcodeproj -scheme WaiSay -destination 'platform=macOS' CODE_SIGNING_ALLOWED=NO build
xcodebuild -project ios/WaiSay/WaiSayiOS.xcodeproj -scheme WaiSay -destination 'generic/platform=iOS Simulator' CODE_SIGNING_ALLOWED=NO build
cd android && ./gradlew --no-daemon testDebugUnitTest assembleDebug
```

## Key Context

- Native iOS/macOS clients own live recording and realtime transcription via `shared/WaiSayKit`.
- Browser auth depends on `AUTH_COOKIE_DOMAIN=say.waiwai.is`; if prod login loops, check cookie domain + CORS first.
- Apple versioning: `MARKETING_VERSION` = human-readable, `CURRENT_PROJECT_VERSION` = monotonic integer build number.

## Observability

- Sentry via `SENTRY_DSN`. Privacy-safe logging mandatory.
- Never log raw emails, tokens, transcript text, search queries, or filenames.
- Backend sanitization: `backend/app/core/observability.py`
- Apple sanitization: `shared/WaiSayKit/Sources/WaiSayKit/Monitoring/SentryHelper.swift`

## Debugging Production

```bash
docker logs waisay-api
docker compose --env-file /etc/waisay/backend.env ps   # in /opt/waisay/backend
```

Prefer fixing recording/realtime issues in shared Swift + backend before touching the web dashboard.
