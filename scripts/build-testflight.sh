#!/bin/bash
set -euo pipefail

# Builds and uploads the iOS WaiSay app to TestFlight.
# (macOS distribution moved to the single Direct DMG channel; see
# scripts/build-macos-dmg.sh + scripts/publish-macos-dmg.sh.)

ROOT_DIR=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT_DIR"

CONFIG_FILE="$APPSTORECONNECT_CONFIG"
KEY_ID=$(/usr/bin/plutil -extract key_id raw -o - "$CONFIG_FILE")
ISSUER_ID=$(/usr/bin/plutil -extract issuer_id raw -o - "$CONFIG_FILE")
KEY_FILEPATH=$(/usr/bin/plutil -extract key_filepath raw -o - "$CONFIG_FILE")
KEY_FILEPATH="${KEY_FILEPATH/#\~/$HOME}"

echo "Building iOS Archive..."
xcodebuild archive \
    -project ios/WaiSay/WaiSayiOS.xcodeproj \
    -scheme WaiSay \
    -configuration Release \
    -archivePath /tmp/WaiSayiOS.xcarchive \
    -allowProvisioningUpdates \
    -authenticationKeyPath "$KEY_FILEPATH" \
    -authenticationKeyID "$KEY_ID" \
    -authenticationKeyIssuerID "$ISSUER_ID"

echo "Preparing Export Options..."
sed 's/<string>export<\/string>/<string>upload<\/string>/g' scripts/export-options/ios-app-store-connect.plist > /tmp/ios-upload.plist

echo "Uploading iOS to TestFlight..."
xcodebuild -exportArchive \
    -archivePath /tmp/WaiSayiOS.xcarchive \
    -exportOptionsPlist /tmp/ios-upload.plist \
    -allowProvisioningUpdates \
    -authenticationKeyPath "$KEY_FILEPATH" \
    -authenticationKeyID "$KEY_ID" \
    -authenticationKeyIssuerID "$ISSUER_ID"

echo "Done — iOS uploaded. macOS DMG is published separately via scripts/build-macos-dmg.sh."
