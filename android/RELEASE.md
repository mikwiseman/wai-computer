# WaiComputer Android — Release runbook

> Last updated: 2026-05-18. App version `1.1.4`, versionCode `13`. Play Console package `is.waiwai.computer`.

## TL;DR

```bash
# Local build (Mac or Linux dev machine with Android SDK + JDK 17):
cd android
./gradlew --no-daemon testDebugUnitTest lint
./gradlew --no-daemon :app:bundleRelease     # → app/build/outputs/bundle/release/app-release.aab
./gradlew --no-daemon :app:assembleRelease   # → app/build/outputs/apk/release/app-release.apk
```

GitHub Actions are intentionally not used for Android release builds in this repo. Release artifacts are built locally from a checked-out, reviewed commit and then uploaded explicitly.

## One-time setup

### Local keystore

1. Generate the upload key once and back it up to 1Password (Vault: `Development`, item: `WaiComputer Android upload key`):

   ```bash
   keytool -genkey -v -keystore android/keystore/upload.jks \
     -keyalg RSA -keysize 2048 -validity 10000 \
     -alias upload -storetype JKS
   ```

2. Create `android/keystore.properties` (already gitignored):

   ```properties
   storeFile=keystore/upload.jks
   storePassword=<set>
   keyAlias=upload
   keyPassword=<set>
   ```

3. Opt in to **Play App Signing** when you upload the first AAB. Google holds the app-signing key; we only ever ship the upload key.

### Play Console listing

1. Create the app in Play Console at `is.waiwai.computer`.
2. Upload assets (see `fastlane/metadata/android/`):
   - `en-US/title.txt`, `short_description.txt`, `full_description.txt`
   - `ru-RU/title.txt`, `short_description.txt`, `full_description.txt`
   - Phone screenshots at `en-US/images/phoneScreenshots/` and `ru-RU/images/phoneScreenshots/` (16:9 or 9:16, 1080×1920 or higher).
   - Feature graphic: 1024×500 PNG.
   - High-res icon: 512×512 PNG.
3. Fill the **Data safety** form (see "Data safety answers" below).
4. Declare `RECORD_AUDIO` use ("Real-time speech transcription for the user's own recordings").

## Per-release flow

1. Bump `versionCode` (must be monotonic) and `versionName` in `android/app/build.gradle.kts`.
2. Commit the bump in its own commit so it shows up cleanly in `git log`.
3. Build locally:
   ```bash
   cd android
   ./gradlew --no-daemon testDebugUnitTest lint
   ./gradlew --no-daemon :app:bundleRelease :app:assembleRelease
   ```
4. Upload `android/app/build/outputs/bundle/release/app-release.aab` to **Internal testing** first. Smoke-test on a real Pixel.
5. Promote to **Closed testing** (~20 testers) for 1-2 weeks.
6. Promote to **Production** with **staged rollout**: 5% → 25% → 100% over a week. Monitor Sentry crash-free rate (>99.5% target).
7. Add the corresponding `fastlane/metadata/android/en-US/changelogs/<versionCode>.txt` and `ru-RU/changelogs/<versionCode>.txt` so Play Console picks up the "What's new" copy on next upload.

## Data safety answers (Play Console form)

| Question | Answer |
|---|---|
| Personal info — Email address | Collected, required for account, encrypted in transit, encrypted at rest, can be deleted by user. |
| App activity — App interactions | Collected, optional, for app functionality + analytics. |
| App info & performance — Crash logs | Collected, optional, for app functionality (Sentry). |
| Audio files — Voice / sound recordings | Collected, required for the core transcription feature; encrypted in transit + at rest; user can delete in-app; shared with speech-to-text providers (Deepgram / ElevenLabs) for the duration of the transcription. |
| Files & docs — Audio import | User picks files via system file picker; not collected outside the import flow. |
| Account deletion | Yes — Settings → Delete account is fully implemented. Also reachable from the web at https://wai.computer/settings. |

## Permissions justification

| Permission | Why we need it |
|---|---|
| `RECORD_AUDIO` | Core feature: record the user's own voice for transcription. |
| `FOREGROUND_SERVICE` + `FOREGROUND_SERVICE_MICROPHONE` | Keep recording alive when the user backgrounds the app or locks the screen. |
| `POST_NOTIFICATIONS` (Android 13+) | Show the persistent foreground-service notification while recording is in progress. Requested at the same moment as `RECORD_AUDIO`. |
| `INTERNET` + `ACCESS_NETWORK_STATE` | Upload recordings, fetch transcripts, run AI chat, detect when offline. |

## Rollback

If a crash spike shows up in the staged rollout:

1. In Play Console → Production → Release dashboard, click **Halt rollout** (stops new installs of the broken build).
2. Either fix forward (bump versionCode, ship a new build) or revert by uploading the previous-known-good AAB as a new release.
3. Never edit a published release in place — Play Console doesn't actually replace the binary even if you re-upload with the same versionCode.

## What's NOT in v1.0 (deferred to v1.1+)

- Voice mode in the Wai chat (ElevenLabs Conversation API)
- Home-screen widget / Quick Settings tile
- Wear OS companion
- Android Auto integration
- Share-extension to receive audio from other apps
