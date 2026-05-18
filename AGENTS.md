# WaiComputer

AI second brain for recordings, transcription, search, and summaries.

## Code style

- No fallbacks. Trust the prompt and the schema; fix the source, not the response.

## Production

- Canonical host: `https://wai.computer`
- API under `/api/*`; health: `GET /health`
- Previous production host retired after the WaiComputer rebrand
- Do not use a separate API hostname; API stays under `/api/*` on `wai.computer`
- Server: `root@157.180.47.68`
- Deploy root: `/opt/waicomputer`
- Runtime env source of truth: `/etc/waicomputer/backend.env`
- `/opt/waicomputer/backend/.env` must be a symlink to `/etc/waicomputer/backend.env`

Keep aligned in env: `FRONTEND_URL=https://wai.computer`, `AUTH_COOKIE_DOMAIN=wai.computer`, `CORS_ORIGINS` includes `https://wai.computer`, `SENTRY_DSN` points at current project.

## Deploy

- GitHub Actions are not used for production deploys or release builds. Do not add push-triggered Actions deploys unless explicitly asked.
- Production deploy (backend + web): `VPS_USER=root ./scripts/deploy-server.sh`.
- Deploy syncs source to `/opt/waicomputer`; the VPS builds `api`, `web`, `celery-worker`, starts `caddy`, and checks health for all four services.
- Runtime env stays only on the server at `/etc/waicomputer/backend.env`; never rebuild it from GitHub secrets.
- **macOS validation before push**: `.git-hooks/pre-push` runs `swift test` + an unsigned `xcodebuild build` automatically on pushes that touch `macos/`, `shared/WaiComputerKit/`, or the macOS release scripts. Install once per clone with `git config core.hooksPath .git-hooks`. Bypass in an emergency with `git push --no-verify`.
- **Continuous validation**: `scripts/qa-loop.sh` is the canonical long-running gate covering backend, web, shared Swift, and native (macOS/iOS/Android) builds. See `README.md` for usage.
- **macOS release**: `VPS_USER=root scripts/release-macos.sh stable|beta` from a Mac with Developer ID, Sparkle EdDSA, and notarization credentials configured. Explicit, manual — no CI button, on purpose. Matches the backend deploy pattern.

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
| `scripts/release-macos.sh stable`              | **stable** |
| `scripts/release-macos.sh beta`                | **beta** |

Day-to-day flow: do work on a feature branch → merge to the desired branch → run the explicit local/server deploy or release command. Pushes do not auto-publish.

### Release flow (typical)

1. Bump `CURRENT_PROJECT_VERSION` in `macos/WaiComputer/project.yml` (monotonic — Sparkle requires it).
2. `cd macos/WaiComputer && xcodegen generate` so `WaiComputer.xcodeproj/project.pbxproj` picks up the new build number.
3. Write `artifacts/releases/macos/<version>-<build>/release-notes.md` BEFORE the bump commit if you want explicit notes, or — more commonly — make sure the commits in this release window are written as user-facing bullets (see "Release notes" below).
4. Commit the version bump. Use the bump commit subject as a marketing summary of the release, not a mechanical "Bump to X.Y.Z" line — it's the fallback shown to every user when no other notes are picked up.
5. Run `VPS_USER=root scripts/release-macos.sh stable|beta` from a Mac with Developer ID, Sparkle, and notarization credentials configured.
6. After ~10-15 min, verify `https://wai.computer/releases/macos/appcast.xml` shows the new `sparkle:version` (and `sparkle:channel` for beta), and open the release notes URL from the appcast in a browser to sanity-check the popup text.

### Release notes

The "What's New" dialog Sparkle shows users comes from `release-notes.md`, published next to the DMG as `https://wai.computer/releases/macos/<version>-<build>/release-notes.md` and linked from the appcast via `<sparkle:releaseNotesLink>`. `scripts/build-macos-dmg.sh` builds that file automatically by harvesting commit subjects since the previous build number bump:

- It locates the previous build's bump commit via `git log -S "CURRENT_PROJECT_VERSION: \"<prev>\""`. **Gotcha:** that match also fires on commits that REMOVE the previous build number, so the heuristic can collapse the window to just the new bump commit when a single PR both edits the version and ships behavior. To avoid this, keep the version bump in its own commit, made AFTER the substantive work has already landed on `main`.
- Within that range it filters `git log --no-merges -- macos/ shared/ scripts/build-macos-dmg.sh` to subjects that do NOT match `^(chore|docs|test|refactor|wip)[(:]`. Anything that survives becomes a `- ...` bullet, capped at 25.
- If the window is empty, it falls back to the single most recent commit subject. That fallback is what users see when the gotcha above bites — write the bump commit accordingly.

Style rules for commit subjects that will surface as release notes:

- **Write for the user, not the reviewer.** "Fix Wai Companion streaming on Russian/emoji text" beats "Refactor CompanionStream byte buffer" — both describe the same change, only one tells the user what's better.
- **Lead with the user-visible verb**: "Add", "Fix", "Improve", "Speed up", "Reduce", "Stop". Avoid "Refactor", "Cleanup", "Bump" unless the change is genuinely internal.
- **One concern per commit.** A commit titled "Fix transcription + add Companion" hides one or both stories in the dialog.
- **Skip the codebase noun.** Users don't know what `APIClient` or `summarizer.py` is. Talk about features (Companion, dictation, recordings).
- **Keep it under ~80 chars** so the line doesn't wrap awkwardly in the popup.
- **Prefix internal-only commits** with `chore:`, `docs:`, `test:`, `refactor:`, or `wip:` so they're filtered out automatically. Use this freely — those filters are the only way to keep noise out of the popup.

If a release genuinely has nothing user-visible to announce (rare for a build worth shipping), at minimum say so: e.g. `Improve background reliability and tighten Sparkle update flow` is honest and useful; `Bump CURRENT_PROJECT_VERSION` is not.

Manual override: edit `artifacts/releases/macos/<version>-<build>/release-notes.md` and rerun only `scripts/publish-macos-dmg.sh <version> <build> stable|beta` — that re-uploads the DMG and notes without rebuilding the app. `scripts/build-macos-dmg.sh` will clobber the file, so always overwrite AFTER the build step or directly edit and publish.

iOS TestFlight notes come from App Store Connect, not the repo — set them in App Store Connect → TestFlight → Test Information after `scripts/build-testflight.sh` finishes the upload, or via `fastlane pilot upload --changelog "..."` if you wire it.

### Appcast merge invariant

`scripts/build-macos-dmg.sh` writes a single-item local appcast. `scripts/publish-macos-dmg.sh` then runs `scripts/merge-macos-appcast.py` to fetch the live remote appcast, dedupe by `(sparkle:version, sparkle:channel)`, cap at 10 items per channel, and upload the merged file. Never bypass the merge — overwriting the remote with a single-item file would erase the other channel's history. Stable and beta artifacts for the same build must have distinct enclosure URLs because their DMGs/signatures can differ; the merge script rejects reused URLs with conflicting `length` / `sparkle:edSignature` metadata.

### macOS release constraints

- Hetzner production is Linux and cannot run `xcodebuild`; signed iOS/macOS artifacts require a Mac build host.
- `scripts/release-macos.sh` builds locally on the Mac and publishes the DMG/appcast to the VPS.
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
docker compose --env-file /etc/waicomputer/backend.env ps   # in /opt/waicomputer/backend
```

Prefer fixing recording/realtime issues in shared Swift + backend before touching the web dashboard.
