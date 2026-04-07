#!/bin/bash
set -e

# Load App Store Connect credentials
CONFIG_FILE=~/.appstoreconnect/config.json
KEY_ID=$(grep '"key_id"' "$CONFIG_FILE" | cut -d '"' -f 4)
ISSUER_ID=$(grep '"issuer_id"' "$CONFIG_FILE" | cut -d '"' -f 4)
KEY_FILEPATH=$(grep '"key_filepath"' "$CONFIG_FILE" | cut -d '"' -f 4)
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
