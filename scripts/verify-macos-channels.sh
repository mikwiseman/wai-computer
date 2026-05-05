#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "$0")/.." && pwd)
PROJECT_PATH="$ROOT_DIR/macos/WaiSay/WaiSay.xcodeproj"
DERIVED_DATA_PATH=${MACOS_CHANNEL_DERIVED_DATA:-"$ROOT_DIR/artifacts/macos-channel-derived-data"}
SWIFTPM_CACHE_PATH=${MACOS_SWIFTPM_CACHE_DIR:-"$ROOT_DIR/artifacts/macos-swiftpm-sourcepackages"}
PACKAGE_RESOLVED="$PROJECT_PATH/project.xcworkspace/xcshareddata/swiftpm/Package.resolved"

if [[ ! -f "$PACKAGE_RESOLVED" ]]; then
  echo "ERROR: missing macOS Package.resolved at $PACKAGE_RESOLVED" >&2
  exit 1
fi

rm -rf "$DERIVED_DATA_PATH"
mkdir -p "$SWIFTPM_CACHE_PATH"

PACKAGE_FLAGS=(
  -clonedSourcePackagesDirPath "$SWIFTPM_CACHE_PATH"
  -disableAutomaticPackageResolution
  -skipPackageUpdates
)

xcodebuild \
  -project "$PROJECT_PATH" \
  -scheme WaiSay \
  -configuration Release \
  -destination 'platform=macOS' \
  -derivedDataPath "$DERIVED_DATA_PATH/appstore" \
  "${PACKAGE_FLAGS[@]}" \
  CODE_SIGNING_ALLOWED=NO \
  build

xcodebuild \
  -project "$PROJECT_PATH" \
  -scheme WaiSayDirect \
  -configuration Release \
  -destination 'platform=macOS' \
  -derivedDataPath "$DERIVED_DATA_PATH/direct" \
  "${PACKAGE_FLAGS[@]}" \
  CODE_SIGNING_ALLOWED=NO \
  build

APPSTORE_APP="$DERIVED_DATA_PATH/appstore/Build/Products/Release/WaiSay.app"
DIRECT_APP="$DERIVED_DATA_PATH/direct/Build/Products/Release/WaiSay.app"
APPSTORE_PLIST="$APPSTORE_APP/Contents/Info.plist"
DIRECT_PLIST="$DIRECT_APP/Contents/Info.plist"

if /usr/libexec/PlistBuddy -c 'Print :SUFeedURL' "$APPSTORE_PLIST" >/dev/null 2>&1; then
  echo "ERROR: App Store build contains SUFeedURL" >&2
  exit 1
fi

if /usr/libexec/PlistBuddy -c 'Print :SUPublicEDKey' "$APPSTORE_PLIST" >/dev/null 2>&1; then
  echo "ERROR: App Store build contains SUPublicEDKey" >&2
  exit 1
fi

if [[ -d "$APPSTORE_APP/Contents/Frameworks/Sparkle.framework" ]]; then
  echo "ERROR: App Store build embeds Sparkle.framework" >&2
  exit 1
fi

DIRECT_FEED=$(/usr/libexec/PlistBuddy -c 'Print :SUFeedURL' "$DIRECT_PLIST")
DIRECT_KEY=$(/usr/libexec/PlistBuddy -c 'Print :SUPublicEDKey' "$DIRECT_PLIST")
if [[ "$DIRECT_FEED" != "https://say.waiwai.is/releases/macos/appcast.xml" ]]; then
  echo "ERROR: direct build has unexpected SUFeedURL: $DIRECT_FEED" >&2
  exit 1
fi

if [[ -z "$DIRECT_KEY" ]]; then
  echo "ERROR: direct build is missing SUPublicEDKey" >&2
  exit 1
fi

if /usr/libexec/PlistBuddy -c 'Print :SUEnableInstallerLauncherService' "$DIRECT_PLIST" >/dev/null 2>&1; then
  echo "ERROR: direct build enables Sparkle installer launcher service despite being unsandboxed" >&2
  exit 1
fi

if [[ ! -d "$DIRECT_APP/Contents/Frameworks/Sparkle.framework" ]]; then
  echo "ERROR: direct build does not embed Sparkle.framework" >&2
  exit 1
fi

echo "macOS channel verification passed"
