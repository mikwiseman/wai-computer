# WaiComputer

AI second brain for recordings, transcription, search, and summaries.

## Production

- Canonical host: `https://wai.computer`
- API under `/api/*`; health: `GET /health`
- Previous production host retired after the WaiComputer rebrand
- Do not use a separate API hostname; API stays under `/api/*` on `wai.computer`
- Server: `<release-user>@<release-host>`
- Deploy root: `<remote-root>`
- Runtime env source of truth: `<remote-env-file>`
- `<remote-root>/backend/.env` must be a symlink to `<remote-env-file>`

Keep aligned in env: `FRONTEND_URL=https://wai.computer`, `AUTH_COOKIE_DOMAIN=wai.computer`, `CORS_ORIGINS` includes `https://wai.computer`, `SENTRY_DSN` points at current project.

## Deploy

- CI deploys on push to `main` when `backend/**`, `web/**`, `shared/**`, `ios/**`, `macos/**`, `android/**`, `scripts/**`, `.github/workflows/deploy.yml`, or `.dockerignore` change.
- Manual: `VPS_USER=<release-user> ./scripts/deploy-api.sh`
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
cd shared/WaiComputerKit && swift test -q
```

Native builds:
```bash
xcodebuild -project macos/WaiComputer/WaiComputer.xcodeproj -scheme WaiComputer -destination 'platform=macOS' CODE_SIGNING_ALLOWED=NO build
xcodebuild -project ios/WaiComputer/WaiComputeriOS.xcodeproj -scheme WaiComputer -destination 'generic/platform=iOS Simulator' CODE_SIGNING_ALLOWED=NO build
cd android && ./gradlew --no-daemon testDebugUnitTest assembleDebug assembleRelease lint
cd android && ./gradlew --no-daemon connectedDebugAndroidTest
```

## Key Context

- Native iOS/macOS clients own live recording and realtime transcription via `shared/WaiComputerKit`.
- Browser auth depends on `AUTH_COOKIE_DOMAIN=wai.computer`; if prod login loops, check cookie domain + CORS first.
- Apple versioning: `MARKETING_VERSION` = human-readable, `CURRENT_PROJECT_VERSION` = monotonic integer build number.

## macOS Distribution

- **Two release channels via single appcast (Sparkle native channels):**
  - **stable** — default. Reaches every macOS user. Items have no `<sparkle:channel>` element.
  - **beta** — opt-in. Items carry `<sparkle:channel>beta</sparkle:channel>`. Only users who toggled "Receive beta updates" in Settings → Updates see them. Implemented via `BetaChannelUpdaterDelegate` returning `Set(["beta"])` from `allowedChannelsForUpdater:` when the `receiveBetaUpdates` UserDefaults key is on.
- Developer ID-signed, notarized DMGs published to `https://wai.computer/releases/macos/`. App Store / TestFlight retired for macOS (iOS still ships via TestFlight).
- One target `WaiComputer` in `macos/WaiComputer/project.yml`. Files: `WaiComputer/Info.plist`, `WaiComputer/WaiComputer.entitlements`. App Sandbox is OFF; Hardened Runtime is ON. Sparkle is always built in (no `#if SPARKLE`).
- Sparkle appcast: `https://wai.computer/releases/macos/appcast.xml`.
- Auth/session persistence on macOS uses file-based storage (`Application Support/WaiComputer/session.json`, mode 0600) via `SessionStore` in `shared/WaiComputerKit` — NOT Keychain. This survives cdhash drift across Sparkle updates.

### Branching → channel mapping

| Trigger                                        | Channel  |
|------------------------------------------------|----------|
| Push to `main` (paths in `macos/`, `shared/WaiComputerKit/`, release scripts) | **stable** |
| Push to `dev`  (same paths)                    | **beta** |
| Tag push `waicomputer-macos-v*`                     | **stable** |
| `gh workflow run "macOS Direct Release"`       | choose `stable` or `beta` via input |

Day-to-day flow: do work on a feature branch → merge into `dev` (auto-publishes a beta the opt-in users will install) → after it bakes, merge `dev` into `main` (auto-publishes the stable build).

If `dev` does not exist locally yet, create it once: `git checkout -b dev && git push -u origin dev`.

### Release flow (typical)

1. Bump `CURRENT_PROJECT_VERSION` in `macos/WaiComputer/project.yml` (monotonic — Sparkle requires it).
2. `cd macos/WaiComputer && xcodegen generate` so `WaiComputer.xcodeproj/project.pbxproj` picks up the new build number.
3. Commit + push to `dev` (beta) or `main` (stable). CI builds, signs, notarizes, and publishes automatically.
4. Or skip the branch route and run `scripts/release-macos.sh stable|beta` to dispatch the workflow manually from any branch.
5. After ~10-15 min, verify `https://wai.computer/releases/macos/appcast.xml` shows the new `sparkle:version` (and `sparkle:channel` for beta).

### Appcast merge invariant

`scripts/build-macos-dmg.sh` writes a single-item local appcast. `scripts/publish-macos-dmg.sh` then runs `scripts/merge-macos-appcast.py` to fetch the live remote appcast, dedupe by `(sparkle:version, sparkle:channel)`, cap at 10 items per channel, and upload the merged file. Never bypass the merge — overwriting the remote with a single-item file would erase the other channel's history. Stable and beta artifacts for the same build must have distinct enclosure URLs because their DMGs/signatures can differ; the merge script rejects reused URLs with conflicting `length` / `sparkle:edSignature` metadata.

### Local fallback (CI unavailable)

- `MACOS_RELEASE_STRICT=1 RELEASE_CHANNEL=stable scripts/build-macos-dmg.sh` then `VPS_USER=<release-user> scripts/publish-macos-dmg.sh`.
- `scripts/make-dmg.sh` is local smoke-only (unsigned, not notarized) and intentionally guarded. Never use it for release artifacts.
- `MACOS_REMOTE_APPCAST_URL` env can override the merge script's source URL for staging or dry runs.

iOS distribution still goes through TestFlight via `scripts/build-testflight.sh`.

## Observability

- Sentry via `SENTRY_DSN`. Privacy-safe logging mandatory.
- Never log raw emails, tokens, transcript text, search queries, or filenames.
- Backend sanitization: `backend/app/core/observability.py`
- Apple sanitization: `shared/WaiComputerKit/Sources/WaiComputerKit/Monitoring/SentryHelper.swift`
- Android sanitization: `android/app/src/main/java/is/waiwai/computer/monitoring/SentryHelper.kt`

## Android

- Production Android DSN lives in `android/gradle.properties` as `wai.sentryDsn`; keep it aligned with the `waicomputer-android` Sentry project.
- Canonical Android magic-link deep link: `waicomputer://magic?token=...`
- Guest recordings are local-first under `filesDir/recordings/`; successful auth must enqueue guest migration sync.
- Before shipping Android work, run unit, lint, release assembly, and connected instrumentation tests.

## Debugging Production

```bash
docker logs waicomputer-api
docker compose --env-file <remote-env-file> ps   # in <remote-root>/backend
```

Prefer fixing recording/realtime issues in shared Swift + backend before touching the web dashboard.
