#!/bin/bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT_DIR"

# Load App Store Connect credentials
CONFIG_FILE="$HOME/.appstoreconnect/config.json"
KEY_ID=$(/usr/bin/plutil -extract key_id raw -o - "$CONFIG_FILE")
ISSUER_ID=$(/usr/bin/plutil -extract issuer_id raw -o - "$CONFIG_FILE")
KEY_FILEPATH=$(/usr/bin/plutil -extract key_filepath raw -o - "$CONFIG_FILE")
KEY_FILEPATH="${KEY_FILEPATH/#\~/$HOME}"

echo "Verifying macOS channel isolation..."
"$ROOT_DIR/scripts/verify-macos-channels.sh"

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

echo "Building macOS Archive..."
xcodebuild archive \
    -project macos/WaiSay/WaiSay.xcodeproj \
    -scheme WaiSay \
    -configuration Release \
    -archivePath /tmp/WaiSayMac.xcarchive \
    -allowProvisioningUpdates \
    -authenticationKeyPath "$KEY_FILEPATH" \
    -authenticationKeyID "$KEY_ID" \
    -authenticationKeyIssuerID "$ISSUER_ID"

echo "Preparing Export Options..."
sed 's/<string>export<\/string>/<string>upload<\/string>/g' scripts/export-options/ios-app-store-connect.plist > /tmp/ios-upload.plist
sed 's/<string>export<\/string>/<string>upload<\/string>/g' scripts/export-options/macos-app-store-connect.plist > /tmp/macos-upload.plist

echo "Uploading iOS to TestFlight..."
xcodebuild -exportArchive \
    -archivePath /tmp/WaiSayiOS.xcarchive \
    -exportOptionsPlist /tmp/ios-upload.plist \
    -allowProvisioningUpdates \
    -authenticationKeyPath "$KEY_FILEPATH" \
    -authenticationKeyID "$KEY_ID" \
    -authenticationKeyIssuerID "$ISSUER_ID"

echo "Uploading macOS to TestFlight..."
xcodebuild -exportArchive \
    -archivePath /tmp/WaiSayMac.xcarchive \
    -exportOptionsPlist /tmp/macos-upload.plist \
    -allowProvisioningUpdates \
    -authenticationKeyPath "$KEY_FILEPATH" \
    -authenticationKeyID "$KEY_ID" \
    -authenticationKeyIssuerID "$ISSUER_ID"

echo "Done!"
