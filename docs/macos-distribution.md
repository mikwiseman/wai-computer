# macOS Direct Distribution

This project ships the mac app as a signed DMG for direct download outside the Mac App Store.

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

- `create-dmg` installed locally, for example `brew install create-dmg`
- `python3` with Pillow available for DMG background composition

Use:

```bash
scripts/build-macos-dmg.sh
```

For a production gate that refuses unsigned runtime paths, use:

```bash
MACOS_RELEASE_STRICT=1 scripts/build-macos-dmg.sh
```

The script:

1. archives the macOS app in `Release`
2. signs it with the configured `Developer ID Application` identity
3. enables the hardened runtime for the archive build
4. optionally notarizes the app payload when explicit credentials are provided
5. creates a signed DMG with a minimal background and `Applications` drop link
6. optionally notarizes and staples the DMG
7. writes a SHA-256 checksum and release metadata file

Artifacts are written under `artifacts/releases/macos/<version>-<build>/`.

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

Strict-release controls:

```bash
export MACOS_RELEASE_STRICT=1          # enables both checks below
export MACOS_REQUIRE_NOTARIZATION=1    # fail if notarization credentials are missing or submit fails
export MACOS_REQUIRE_GATEKEEPER=1      # fail if spctl rejects the app or DMG
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

In strict mode, Gatekeeper and notarization failures stop the build instead of being reported as warnings.

## User Install Flow

1. Open the DMG.
2. Drag `WaiSay.app` into `Applications`.
3. Eject the DMG.
4. Launch `WaiSay` from `/Applications`.

## Apple references

- Notarizing macOS software before distribution: https://developer.apple.com/documentation/security/notarizing_macos_software_before_distribution
- Customizing the notarization workflow: https://developer.apple.com/documentation/security/customizing-the-notarization-workflow
- Distribute outside the Mac App Store: https://help.apple.com/xcode/mac/current/en.lproj/dev033e997ca.html
