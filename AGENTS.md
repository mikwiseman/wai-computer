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
cd android && ./gradlew --no-daemon testDebugUnitTest assembleDebug assembleRelease lint
cd android && ./gradlew --no-daemon connectedDebugAndroidTest
```

## Key Context

- Native iOS/macOS clients own live recording and realtime transcription via `shared/WaiSayKit`.
- Browser auth depends on `AUTH_COOKIE_DOMAIN=say.waiwai.is`; if prod login loops, check cookie domain + CORS first.
- Apple versioning: `MARKETING_VERSION` = human-readable, `CURRENT_PROJECT_VERSION` = monotonic integer build number.

## macOS Distribution

- **Single channel: Developer ID-signed, notarized DMG with Sparkle auto-update.** App Store / TestFlight retired for macOS (iOS still ships via TestFlight).
- One target `WaiSay` in `macos/WaiSay/project.yml`. Files: `WaiSay/Info.plist`, `WaiSay/WaiSay.entitlements`. App Sandbox is OFF; Hardened Runtime is ON. Sparkle is always built in (no `#if SPARKLE`).
- Release artifacts publish to `https://say.waiwai.is/releases/macos/`. Sparkle appcast: `https://say.waiwai.is/releases/macos/appcast.xml`.
- Auth/session persistence on macOS uses file-based storage (`Application Support/WaiSay/session.json`, mode 0600) via `SessionStore` in `shared/WaiSayKit` — NOT Keychain. This survives cdhash drift across Sparkle updates.
- Production release flow:
  1. Bump `CURRENT_PROJECT_VERSION` in `macos/WaiSay/project.yml` (monotonic — Sparkle requires it).
  2. `cd macos/WaiSay && xcodegen generate` so `WaiSay.xcodeproj/project.pbxproj` picks up the new build number.
  3. Commit + push.
  4. Trigger CI: `gh workflow run "macOS Direct Release" --ref main -f publish_web=true`.
  5. After ~10-15 min, verify `https://say.waiwai.is/releases/macos/appcast.xml` shows the new `sparkle:version`.
- `.github/workflows/macos-release.yml` triggers ONLY on `workflow_dispatch` or `push` of a `waisay-macos-v*` tag. **Push to `main` does NOT auto-publish a DMG.**
- Local release fallback (CI unavailable): `MACOS_RELEASE_STRICT=1 scripts/build-macos-dmg.sh` then `VPS_USER=root scripts/publish-macos-dmg.sh`, or `VPS_USER=root fastlane mac upload_all`.
- `scripts/make-dmg.sh` is local smoke-only (unsigned, not notarized) and intentionally guarded. Never use it for release artifacts.
- iOS distribution still goes through TestFlight via `scripts/build-testflight.sh`.

## Observability

- Sentry via `SENTRY_DSN`. Privacy-safe logging mandatory.
- Never log raw emails, tokens, transcript text, search queries, or filenames.
- Backend sanitization: `backend/app/core/observability.py`
- Apple sanitization: `shared/WaiSayKit/Sources/WaiSayKit/Monitoring/SentryHelper.swift`
- Android sanitization: `android/app/src/main/java/is/waiwai/say/monitoring/SentryHelper.kt`

## Android

- Production Android DSN lives in `android/gradle.properties` as `wai.sentryDsn`; keep it aligned with the `waisay-android` Sentry project.
- Canonical Android magic-link deep link: `waisay://magic?token=...`
- Guest recordings are local-first under `filesDir/recordings/`; successful auth must enqueue guest migration sync.
- Before shipping Android work, run unit, lint, release assembly, and connected instrumentation tests.

## Debugging Production

```bash
docker logs waisay-api
docker compose --env-file /etc/waisay/backend.env ps   # in /opt/waisay/backend
```

Prefer fixing recording/realtime issues in shared Swift + backend before touching the web dashboard.
