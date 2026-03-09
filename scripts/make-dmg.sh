#!/bin/bash
# Quick DMG build for WaiComputer (works from Claude Code and Terminal)
# Usage: ./scripts/make-dmg.sh
#
# Uses ditto --noextattr + /tmp mountpoint to avoid macOS provenance
# attribute issues that block cp/hdiutil in non-Terminal processes.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
XCODE_PROJECT="$PROJECT_DIR/macos/WaiComputer/WaiComputer.xcodeproj"
DMG_PATH="/tmp/WaiComputer.dmg"
MOUNT_POINT="/tmp/wai_dmg_mount"
STAGING="/tmp/wai_dmg_staging"
SPARSE="/tmp/WaiComputer_rw.sparseimage"

echo "==> Building Release..."
xcodebuild -project "$XCODE_PROJECT" \
    -scheme WaiComputer \
    -configuration Release \
    build -quiet 2>&1 | grep -v "warning:\|note:" || true

APP_SRC="$(xcodebuild -project "$XCODE_PROJECT" -scheme WaiComputer -configuration Release -showBuildSettings 2>/dev/null | grep ' BUILT_PRODUCTS_DIR =' | awk '{print $3}')/WaiComputer.app"

echo "==> Staging app..."
rm -rf "$STAGING"
mkdir -p "$STAGING"
ditto "$APP_SRC" "$STAGING/WaiComputer.app"

echo "==> Creating DMG..."
rm -f "$SPARSE" "$DMG_PATH"
hdiutil create -size 300m -fs HFS+ -volname "WaiComputer" -type SPARSE "${SPARSE%.sparseimage}"

rm -rf "$MOUNT_POINT" && mkdir -p "$MOUNT_POINT"
hdiutil attach "$SPARSE" -mountpoint "$MOUNT_POINT"

ditto --noextattr --noqtn "$STAGING/WaiComputer.app" "$MOUNT_POINT/WaiComputer.app"
ln -s /Applications "$MOUNT_POINT/Applications"

hdiutil detach "$MOUNT_POINT"
hdiutil convert "$SPARSE" -format UDZO -o "$DMG_PATH"

rm -f "$SPARSE"
rm -rf "$STAGING" "$MOUNT_POINT"

echo ""
echo "==> DMG ready: $DMG_PATH"
ls -lh "$DMG_PATH"
