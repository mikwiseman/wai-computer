# WaiComputer

AI second brain for recordings, transcription, search, and summaries.

## Code style

- No fallbacks. Trust the prompt and the schema; fix the source, not the response.
- Do not add extra fallback paths. Add one only when it is required for a critical user recovery path, and make it explicit to the user.

## Production

- Canonical host: `https://wai.computer` (API at `/api/*`, health at `/health`). No separate API hostname.
- In-app MCP connect instructions live in Settings → MCP on every platform; the displayed URL is the hardcoded prod canonical `https://wai.computer/mcp`.
- Server: `<release-user>@<release-host>`, deploy root `<remote-root>`.
- Runtime env: `<remote-env-file>` is the source of truth; `<remote-root>/backend/.env` is a symlink to it.
- Keep aligned: `FRONTEND_URL=https://wai.computer`, `AUTH_COOKIE_DOMAIN=wai.computer`, `CORS_ORIGINS` includes `https://wai.computer`, `SENTRY_DSN` on the current project.

## Deploy

- No CI deploys. Backend + web: `VPS_USER=<release-user> ./scripts/deploy-server.sh` (builds `api`/`web`/`celery-worker` on the VPS, waits for health).
- Runtime env stays only on the server at `<remote-env-file>`; never rebuild it from secrets.
- Pre-push hook: `git config core.hooksPath .git-hooks` once; runs `swift test` + unsigned macOS `xcodebuild build` on Apple-touching pushes. `--no-verify` to bypass.
- Long-running gate: `scripts/qa-loop.sh` (backend + web + Swift + native). See `README.md`.
- macOS release: `VPS_USER=<release-user> scripts/release-macos.sh stable|beta` from a Mac with Developer ID, Sparkle EdDSA, and notarization configured.

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
cd android && ./gradlew --no-daemon testDebugUnitTest assembleDebug assembleRelease lint
cd android && ./gradlew --no-daemon connectedDebugAndroidTest
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
- Releases need a Mac host (Linux VPS can't `xcodebuild`). `scripts/make-dmg.sh` is unsigned smoke only — never use for releases. `MACOS_REMOTE_APPCAST_URL` overrides the merge source for staging.

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

## Windows

- Tech: `.NET 9` + `WinUI 3` (Windows App SDK 1.6+); targets Win10 1809+ and Win11; x64-only in v1.0.
- Layout: `desktop/WaiComputer.Core/` (portable `net9.0` business logic — builds on any OS), `desktop/WaiComputer.Core.Tests/` (portable tests), and `windows/WaiComputer/` (the WinUI 3 app — Win-only). Native/UI tests remain under `windows/WaiComputer.{Native,UI}.Tests/`.
- Local dev: macOS users run a Parallels Win 11 VM with VS 2022 + Windows App SDK workload; mount `windows/` via Parallels Shared Folders. See `windows/PARALLELS.md`.
- Audio: `NAudio.Wasapi` for mic + `WasapiLoopbackCapture` for system audio; 16 kHz mono int16, frame size 1600 samples.
- Hotkey: `SetWindowsHookEx WH_KEYBOARD_LL` for global push-to-talk (default RightAlt). No Accessibility-equivalent privacy permission required on Windows.
- Text insertion: clipboard + `SendInput Ctrl+V`. Fallback message identical to macOS: "Text is on your clipboard — press Ctrl+V to paste manually."
- Session storage: `%APPDATA%\WaiComputer\session.json`, encrypted via DPAPI (`CurrentUser` scope); file ACL trimmed to current user only.
- Magic link: `waicomputer://auth/verify?token=...` registered in `HKCU\Software\Classes`; single-instance redirect via `AppInstance`.
- Auto-update: Velopack, separate `releases.win.json` (stable) + `releases.win.beta.json` (beta) feeds at `https://wai.computer/releases/windows/`.
- Code signing: Azure Trusted Signing — `vpk pack --azureTrustedSigning ...`. Sign `.exe`, `Setup.exe`, and `.nupkg`.
- Release: `scripts/release-windows.ps1 stable|beta` (PowerShell, run inside the Win VM with Az credentials + SSH key to VPS).
- Sentry: separate `waicomputer-windows` project; DSN in `windows/WaiComputer/appsettings.json`. Same PII sanitisation rules as Mac+Android (`Sanitizer.cs`).
- Tests: TDD-first. `WaiComputer.Core.Tests` is portable and can run on macOS via `dotnet test`; `WaiComputer.Native.Tests` and `WaiComputer.UITests` need a Win host. Coverage gate ≥85% on `Core/`.

Native builds:
```powershell
dotnet test desktop/WaiComputer.Core.Tests
cd windows
dotnet restore
dotnet build -c Release
dotnet test WaiComputer.Native.Tests
dotnet test WaiComputer.UITests
```

## Linux

- Tech: `.NET 9` + Avalonia; x64-only in v1.
- Layout: `linux/WaiComputer.Linux/` (Avalonia app), `linux/WaiComputer.Linux.Tests/` (Linux platform tests), shared portable code in `desktop/WaiComputer.Core/`.
- Audio: user-space PulseAudio protocol on PipeWire/PulseAudio via `pactl` and `parec`; system audio requires an exposed monitor source for the active sink.
- Hotkey: Wayland requires `org.freedesktop.portal.GlobalShortcuts`; X11 uses the XGrabKey path. Unsupported sessions must show an explicit disabled state.
- Text insertion: Wayland requires RemoteDesktop + Clipboard portals; X11 requires clipboard + XTest-compatible tools. Recovery copy message: "Text is on your clipboard - press Ctrl+V to paste manually."
- Session storage: freedesktop Secret Service via `secret-tool`; never store Linux auth tokens in plaintext files.
- Magic link: `waicomputer://auth/verify?token=...` through `x-scheme-handler/waicomputer` in the `.desktop` file.
- Auto-update: Velopack AppImage, channels `linux` (stable) and `linux-beta` (beta), feed root `https://wai.computer/releases/linux/`.
- Release: `scripts/release-linux.sh stable|beta` on a Linux x64 host with .NET 9 SDK and Velopack CLI `0.0.1298`; set `LINUX_RELEASE_PUBLISH=1 VPS_USER=<release-user>` to upload to the VPS.

Native builds:
```bash
cd linux
dotnet restore WaiComputer.Linux.sln
dotnet test WaiComputer.Linux.Tests
dotnet publish WaiComputer.Linux/WaiComputer.Linux.csproj -c Release -r linux-x64 --self-contained true
```

## Debugging Production

```bash
docker logs waicomputer-api
docker compose --env-file <remote-env-file> ps   # in <remote-root>/backend
```

Prefer fixing recording/realtime issues in shared Swift + backend before touching the web dashboard.
