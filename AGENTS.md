# WaiComputer

AI second brain for recordings, transcription, search, and summaries.

## Code style

- No fallbacks. Trust the prompt and the schema; fix the source, not the response.
- Do not add extra fallback paths. Add one only when it is required for a critical user recovery path, and make it explicit to the user.

## Production

- Canonical host: `https://wai.computer` (API at `/api/*`, health at `/health`). No separate API hostname.
- DNS points at the **wai-ru edge proxy** (`root@63.250.57.133`, Caddy configs in `/etc/caddy/sites-enabled/`), which terminates TLS + HTTP/3 and reverse-proxies to the origin below over TCP. Debug edge-vs-origin issues by comparing responses from both (origin direct: `curl --resolve wai.computer:443:157.180.47.68 …`).
- In-app MCP connect instructions live in Settings → MCP on every platform; the displayed URL is the hardcoded prod canonical `https://wai.computer/mcp`.
- Server: `root@157.180.47.68`, deploy root `/opt/waicomputer`.
- Runtime env: `/etc/waicomputer/backend.env` is the source of truth; `/opt/waicomputer/backend/.env` is a symlink to it.
- Keep aligned: `FRONTEND_URL=https://wai.computer`, `AUTH_COOKIE_DOMAIN=wai.computer`, `CORS_ORIGINS` includes `https://wai.computer`, `SENTRY_DSN` on the current project.

## Deploy

- No CI deploys. Backend + web: `VPS_USER=root ./scripts/deploy-server.sh` (builds `api`/`web`/`celery-worker` on the VPS, waits for health).
- Runtime env stays only on the server at `/etc/waicomputer/backend.env`; never rebuild it from secrets.
- Pre-push hook: `git config core.hooksPath .git-hooks` once; runs `swift test` + unsigned macOS `xcodebuild build` on Apple-touching pushes. `--no-verify` to bypass.
- Long-running gate: `scripts/qa-loop.sh` (backend + web + Swift + native). See `README.md`.
- macOS release: `VPS_USER=root scripts/release-macos.sh stable|beta` from a Mac with Developer ID, Sparkle EdDSA, and notarization configured.

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

Use these commands as a verification menu, not as an every-build checklist. For
normal local work, run the smallest repo-native check that proves the changed
behavior, plus lint/format checks for the touched surface when useful. Run
broader suites for shared critical paths, risky changes, and release/deploy
work. `scripts/qa-loop.sh` is a long-running release/stability gate, not a
routine build gate.

```bash
cd backend && pytest -x -q           # unit (95% coverage gate; see pyproject cov-fail-under)
cd backend && pytest -m integration --no-cov
cd backend && ruff check .
cd web && pnpm lint && pnpm test:unit && pnpm test:e2e
cd shared/WaiComputerKit && swift test -q
```

Native builds:
```bash
xcodebuild -project macos/WaiComputer/WaiComputer.xcodeproj -scheme WaiComputer -destination 'platform=macOS' CODE_SIGNING_ALLOWED=NO build
xcodebuild -project ios/WaiComputer/WaiComputeriOS.xcodeproj -scheme WaiComputer -destination 'generic/platform=iOS Simulator' CODE_SIGNING_ALLOWED=NO build
```

## Key Context

- Native iOS/macOS clients own live recording and realtime transcription via `shared/WaiComputerKit`.
- Browser auth depends on `AUTH_COOKIE_DOMAIN=wai.computer`; if prod login loops, check cookie domain + CORS first.
- Apple versioning: `MARKETING_VERSION` = human-readable, `CURRENT_PROJECT_VERSION` = monotonic integer build number.

## macOS Distribution

- Two channels via one appcast: **stable** (no `<sparkle:channel>` element, reaches everyone) and **beta** (`<sparkle:channel>beta</sparkle:channel>`, opt-in via Settings → Updates).
- Developer ID-signed, notarized DMGs at `https://wai.computer/releases/macos/`; appcast at `appcast.xml` next to them. iOS still ships via TestFlight (`scripts/build-testflight.sh`).
- One target `WaiComputer` in `macos/WaiComputer/project.yml`. App Sandbox OFF, Hardened Runtime ON, Sparkle always built in.
- Auth/session uses file storage (`Application Support/WaiComputer/session.json`, mode 0600) via `SessionStore`, NOT Keychain — survives cdhash drift across updates.
- "What's New" auto-bullets commit subjects since the previous build bump (skips `chore:|docs:|test:|refactor:|wip:`); keep the bump in its own commit AFTER the work, or override `artifacts/releases/macos/<version>-<build>/release-notes.md` and rerun `scripts/publish-macos-dmg.sh`.
- Release: bump `CURRENT_PROJECT_VERSION` in `project.yml` (monotonic) → `cd macos/WaiComputer && xcodegen generate` → commit → `scripts/release-macos.sh stable|beta` → verify `appcast.xml` after ~10–15 min.
- Appcast merge: `publish-macos-dmg.sh` runs `merge-macos-appcast.py` to dedupe by `(sparkle:version, sparkle:channel)` and cap 10 items per channel; never overwrite the remote with a single-item file. Stable + beta of the same build need distinct enclosure URLs.
- Releases need a Mac host; the production VPS can't `xcodebuild`. `scripts/make-dmg.sh` is unsigned smoke only — never use for releases. `MACOS_REMOTE_APPCAST_URL` overrides the merge source for staging.

## Observability

- Sentry via `SENTRY_DSN`. Privacy-safe logging mandatory.
- Never log raw emails, tokens, transcript text, search queries, or filenames.
- Backend sanitization: `backend/app/core/observability.py`
- Apple sanitization: `shared/WaiComputerKit/Sources/WaiComputerKit/Monitoring/SentryHelper.swift`

## Debugging Production

```bash
docker logs waicomputer-api
docker compose --env-file /etc/waicomputer/backend.env ps   # in /opt/waicomputer/backend
```

For stale recording recovery incidents, confirm the scheduler and worker before
touching app code:

```bash
cd /opt/waicomputer/backend
docker compose --env-file /etc/waicomputer/backend.env logs celery-worker --tail=200
docker compose --env-file /etc/waicomputer/backend.env exec celery-worker \
  celery -A app.tasks.celery_app:celery_app inspect ping --timeout=5
docker compose --env-file /etc/waicomputer/backend.env exec celery-worker \
  celery -A app.tasks.celery_app:celery_app call \
  app.tasks.recording_audio_processing.recover_stale_recording_processing
```

Record the stuck counts, oldest `processing`/`uploading` timestamps, and whether
the worker beat loop is publishing `recording-processing-recovery-every-minute`.
If the sweep is not running, fix beat or worker routing first; do not ask users
to retry before checking local client recovery files.

Prefer fixing recording/realtime issues in shared Swift + backend before touching the web dashboard.
