#!/bin/bash
set -euo pipefail

# Builds and uploads the iOS WaiComputer app to TestFlight.
# (macOS distribution moved to the single Direct DMG channel; see
# scripts/build-macos-dmg.sh + scripts/publish-macos-dmg.sh.)

ROOT_DIR=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT_DIR"

CONFIG_FILE="$APPSTORECONNECT_CONFIG"
KEY_ID=$(/usr/bin/plutil -extract key_id raw -o - "$CONFIG_FILE")
ISSUER_ID=$(/usr/bin/plutil -extract issuer_id raw -o - "$CONFIG_FILE")
KEY_FILEPATH=$(/usr/bin/plutil -extract key_filepath raw -o - "$CONFIG_FILE")
KEY_FILEPATH="${KEY_FILEPATH/#\~/$HOME}"

# The repo keeps the Apple team as a placeholder in project.yml AND in the
# export-options plist (so the real team id is never committed). Inject it at
# release time on the archive command + into the export plist (mirrors how
# release-macos.sh injects MACOS_TEAM_ID).
APPLE_TEAM_ID="${APPLE_TEAM_ID:?APPLE_TEAM_ID is required (the Apple Developer team id, e.g. R4A779QVVY)}"

# Sentry dSYM upload needs an auth token; self-load from 1Password if unset
# (mirrors scripts/release-macos.sh).
if [[ -z "${SENTRY_AUTH_TOKEN:-}" ]]; then
  if SENTRY_AUTH_TOKEN_LOADED=$(op read "op://Development/Sentry WaiComputer/password" 2>/dev/null) \
     && [[ -n "$SENTRY_AUTH_TOKEN_LOADED" ]]; then
    export SENTRY_AUTH_TOKEN="$SENTRY_AUTH_TOKEN_LOADED"
    unset SENTRY_AUTH_TOKEN_LOADED
    echo "✓ Loaded SENTRY_AUTH_TOKEN from 1Password (op://Development/Sentry WaiComputer)"
  fi
  if [[ -z "${SENTRY_AUTH_TOKEN:-}" ]]; then
    echo "ERROR: SENTRY_AUTH_TOKEN is required for the iOS dSYM upload." >&2
    echo "         export SENTRY_AUTH_TOKEN=\$(op read 'op://Development/Sentry WaiComputer/password')" >&2
    exit 1
  fi
fi

echo "Building iOS Archive..."
xcodebuild archive \
    -project ios/WaiComputer/WaiComputeriOS.xcodeproj \
    -scheme WaiComputer \
    -configuration Release \
    -archivePath /tmp/WaiComputeriOS.xcarchive \
    -allowProvisioningUpdates \
    -authenticationKeyPath "$KEY_FILEPATH" \
    -authenticationKeyID "$KEY_ID" \
    -authenticationKeyIssuerID "$ISSUER_ID" \
    DEVELOPMENT_TEAM="$APPLE_TEAM_ID"

echo "Uploading iOS dSYMs to Sentry..."
"$ROOT_DIR/scripts/sentry-upload-debug-files.sh" waicomputer-ios /tmp/WaiComputeriOS.xcarchive/dSYMs

echo "Preparing Export Options..."
# destination export -> upload, and substitute the placeholder team id (the
# committed plist has a literal <apple-team-id> which is also invalid XML).
sed -e 's/<string>export<\/string>/<string>upload<\/string>/g' \
    -e "s/<apple-team-id>/$APPLE_TEAM_ID/g" \
    scripts/export-options/ios-app-store-connect.plist > /tmp/ios-upload.plist

echo "Uploading iOS to TestFlight..."
xcodebuild -exportArchive \
    -archivePath /tmp/WaiComputeriOS.xcarchive \
    -exportOptionsPlist /tmp/ios-upload.plist \
    -allowProvisioningUpdates \
    -authenticationKeyPath "$KEY_FILEPATH" \
    -authenticationKeyID "$KEY_ID" \
    -authenticationKeyIssuerID "$ISSUER_ID"

echo "Done — iOS uploaded. macOS DMG is published separately via scripts/build-macos-dmg.sh."
