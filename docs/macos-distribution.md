# macOS Direct Distribution

This project ships the mac app as a signed DMG for direct download outside the Mac App Store.

WaiSay has two macOS channels:

- `WaiSay` is the Mac App Store/TestFlight target. It is sandboxed and must not include Sparkle or any `SU*` update keys.
- `WaiSayDirect` is the direct-download target. It uses the same bundle ID, embeds Sparkle, and checks `https://say.waiwai.is/releases/macos/appcast.xml`.

## Best-practice baseline

- Sign the app with `Developer ID Application`.
- Enable the hardened runtime for the release archive.
- Notarize the app payload and the final DMG.
- Staple the notarization ticket so first-run validation does not depend on a live network check.
- Keep the DMG window simple: app icon, `Applications` drop link, a clear drag instruction, and no extra clutter.
- Publish a checksum next to the DMG.

`Developer ID Installer` is only needed for `.pkg` installers. It is not required for a DMG-based app release.

## Script

Prerequisites:

- Xcode command-line tools available for `xcodebuild`, `codesign`, `hdiutil`, `xcrun`, and `ditto`

Use:

```bash
scripts/build-macos-dmg.sh
```

For a production gate that refuses unsigned runtime paths, use:

```bash
MACOS_RELEASE_STRICT=1 scripts/build-macos-dmg.sh
```

The script:

1. archives the direct-distribution macOS app with the `WaiSayDirect` scheme in `Release`
2. signs it with the configured `Developer ID Application` identity
3. enables the hardened runtime for the archive build
4. re-signs Sparkle nested helper code for Developer ID distribution
5. notarizes the app payload when credentials are provided by env vars or `$APPSTORECONNECT_CONFIG`
6. creates a signed DMG with a minimal background and `Applications` drop link
7. notarizes and staples the DMG when notarization credentials are available
8. signs the DMG update with Sparkle EdDSA and writes `appcast.xml`
9. writes a SHA-256 checksum and release metadata file

Artifacts are written under `artifacts/releases/macos/<version>-<build>/`. The latest appcast and convenience aliases are written under `artifacts/releases/macos/`.

### Custom DMG background

The build keeps a consistent installer layout even when you supply custom art.

- Default behavior: generate a ready-to-use background with instruction text and drag arrow
- Custom behavior: pass `MACOS_DMG_BACKGROUND=/absolute/path/background.png` and the script will compose that art into the same DMG layout

Recommended background input:

- `960x620` PNG
- minimal art with clear left and right negative space for the app icon and `Applications` alias
- no embedded text or arrows in the AI source image; the packaging script adds those deterministically

Examples:

```bash
# Preview the stock composed background
scripts/render-macos-dmg-background.sh /tmp/wai-dmg-bg.png

# Build a DMG with custom art while keeping the install guidance overlay
MACOS_DMG_BACKGROUND=/absolute/path/wai-dmg-bg.png scripts/build-macos-dmg.sh
```

## Environment variables

Signing defaults are set for the current WaiWai team and can be overridden:

```bash
export MACOS_TEAM_ID=<apple-team-id>
export MACOS_SIGNING_IDENTITY='Developer ID Application: WaiWai, LLC (<apple-team-id>)'
```

Notarization is only attempted when one of these credential modes is provided:

```bash
export NOTARY_KEYCHAIN_PROFILE='wai-notary'
```

or

```bash
export NOTARY_KEY="$HOME/.appstoreconnect/private_keys/AuthKey_XXXXXXXXXX.p8"
export NOTARY_KEY_ID='XXXXXXXXXX'
export NOTARY_ISSUER='00000000-0000-0000-0000-000000000000' # omit for individual keys
```

If neither mode is provided, the script reads `$APPSTORECONNECT_CONFIG` by default and uses `key_filepath`, `key_id`, and `issuer_id` from that file. Set `APPSTORECONNECT_CONFIG=/absolute/path/config.json` to use a different config.

Strict-release controls:

```bash
export MACOS_RELEASE_STRICT=1          # enables both checks below
export MACOS_REQUIRE_NOTARIZATION=1    # fail if notarization credentials are missing or submit fails
export MACOS_REQUIRE_GATEKEEPER=1      # fail if spctl rejects the app or DMG
export MACOS_REQUIRE_SPARKLE_SIGNATURE=1 # fail if the appcast cannot be signed
```

Build controls:

```bash
export MACOS_SCHEME=WaiSayDirect       # default direct-distribution scheme
export MACOS_CONFIGURATION=Release     # default build configuration
```

Sparkle controls:

```bash
export MACOS_SPARKLE_DOWNLOAD_BASE_URL=https://say.waiwai.is/releases/macos
export MACOS_SPARKLE_FEED_URL=https://say.waiwai.is/releases/macos/appcast.xml
export SPARKLE_KEYCHAIN_ACCOUNT=is.waiwai.say.sparkle
export SPARKLE_PRIVATE_KEY_FILE=/absolute/path/private-key # or SPARKLE_PRIVATE_KEY in CI
```

For clean developer-machine QA before validating a release build:

```bash
scripts/reset-macos-app-state.sh
```

## Output verification

The script verifies:

- app signature with `codesign --verify --deep --strict`
- DMG signature with `codesign --verify`
- DMG integrity with `hdiutil verify`
- Gatekeeper assessment with `spctl`
- Sparkle appcast signing in strict mode

The channel split can be verified without signing:

```bash
scripts/verify-macos-channels.sh
```

In strict mode, Gatekeeper and notarization failures stop the build instead of being reported as warnings.

Do not use `scripts/make-dmg.sh` for a release. It is intentionally guarded as a local unsigned/unnotarized smoke helper and uses `WaiSayDirect` only when `MACOS_ALLOW_LOCAL_UNNOTARIZED_DMG=1` is set.

## Publish to web

After building a strict release, publish the versioned DMG, checksum, release notes, and appcast to the production host:

```bash
VPS_USER=<release-user> scripts/publish-macos-dmg.sh
```

Fastlane can run the complete macOS release sequence:

```bash
VPS_USER=<release-user> fastlane mac upload_all
```

This uploads the Mac App Store build to TestFlight, then builds and publishes the direct DMG channel.

If a TestFlight install shows `"WaiSay" No Longer Available`, first verify the build state in App Store Connect. If the latest macOS build is still valid and in beta testing, remove the stale TestFlight install from `/Applications` and reinstall/update from TestFlight. Do not install the direct DMG over a TestFlight copy unless you are intentionally switching channels.

## GitHub Actions release

The `macOS Direct Release` workflow builds a strict notarized DMG, uploads the artifact, and can publish it to `say.waiwai.is`.

Required repository secrets:

- `APPLE_CERTIFICATE`: base64-encoded Developer ID Application `.p12`
- `APPLE_CERTIFICATE_PASSWORD`: password for that `.p12`
- `APPLE_API_PRIVATE_KEY`: App Store Connect `.p8` private key contents
- `APPLE_API_KEY_ID`: App Store Connect API key ID
- `APPLE_API_ISSUER_ID`: App Store Connect issuer ID
- `SPARKLE_PRIVATE_KEY`: Sparkle EdDSA private key
- `VPS_HOST`, `VPS_USER`, `VPS_SSH_KEY`: publishing SSH credentials

## User Install Flow

1. Open the DMG.
2. Drag `WaiSay.app` into `Applications`.
3. Eject the DMG.
4. Launch `WaiSay` from `/Applications`.

## Apple references

- Notarizing macOS software before distribution: https://developer.apple.com/documentation/security/notarizing_macos_software_before_distribution
- Customizing the notarization workflow: https://developer.apple.com/documentation/security/customizing-the-notarization-workflow
- Distribute outside the Mac App Store: https://help.apple.com/xcode/mac/current/en.lproj/dev033e997ca.html
