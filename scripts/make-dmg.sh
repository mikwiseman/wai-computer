#!/bin/bash
# Local-only unsigned DMG smoke build for WaiSay.
# Production DMG releases must use scripts/build-macos-dmg.sh so the app is
# Developer ID signed, notarized, stapled, Sparkle-signed, and publishable.
#
# Usage:
#   MACOS_ALLOW_LOCAL_UNNOTARIZED_DMG=1 ./scripts/make-dmg.sh
#
# Uses ditto --noextattr + /tmp mountpoint to avoid macOS provenance
# attribute issues that block cp/hdiutil in non-Terminal processes.
set -euo pipefail

if [[ "${MACOS_ALLOW_LOCAL_UNNOTARIZED_DMG:-0}" != "1" ]]; then
    cat >&2 <<'EOF'
ERROR: scripts/make-dmg.sh creates only a local unsigned/unnotarized DMG.

For production, run:
  MACOS_RELEASE_STRICT=1 scripts/build-macos-dmg.sh

For a local smoke DMG, run:
  MACOS_ALLOW_LOCAL_UNNOTARIZED_DMG=1 scripts/make-dmg.sh
EOF
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
XCODE_PROJECT="$PROJECT_DIR/macos/WaiSay/WaiSay.xcodeproj"
SCHEME="WaiSay"
DMG_PATH="/tmp/WaiSay.dmg"
MOUNT_POINT="/tmp/wai_dmg_mount"
STAGING="/tmp/wai_dmg_staging"
SPARSE="/tmp/WaiSay_rw.sparseimage"

echo "==> Building Release..."
set +e
BUILD_OUTPUT=$(xcodebuild -project "$XCODE_PROJECT" \
    -scheme "$SCHEME" \
    -configuration Release \
    CODE_SIGNING_ALLOWED=NO \
    build -quiet 2>&1)
BUILD_STATUS=$?
set -e
printf '%s\n' "$BUILD_OUTPUT" | grep -v "warning:\|note:" || true
if [[ "$BUILD_STATUS" -ne 0 ]]; then
    exit "$BUILD_STATUS"
fi

APP_SRC="$(xcodebuild -project "$XCODE_PROJECT" -scheme "$SCHEME" -configuration Release -showBuildSettings 2>/dev/null | grep ' BUILT_PRODUCTS_DIR =' | awk '{print $3}')/WaiSay.app"

echo "==> Staging app..."
rm -rf "$STAGING"
mkdir -p "$STAGING"
ditto "$APP_SRC" "$STAGING/WaiSay.app"

echo "==> Creating DMG..."
rm -f "$SPARSE" "$DMG_PATH"
hdiutil create -size 300m -fs HFS+ -volname "WaiSay" -type SPARSE "${SPARSE%.sparseimage}"

rm -rf "$MOUNT_POINT" && mkdir -p "$MOUNT_POINT"
hdiutil attach "$SPARSE" -mountpoint "$MOUNT_POINT"

ditto --noextattr --noqtn "$STAGING/WaiSay.app" "$MOUNT_POINT/WaiSay.app"
ln -s /Applications "$MOUNT_POINT/Applications"

hdiutil detach "$MOUNT_POINT"
hdiutil convert "$SPARSE" -format UDZO -o "$DMG_PATH"

rm -f "$SPARSE"
rm -rf "$STAGING" "$MOUNT_POINT"

echo ""
echo "==> DMG ready: $DMG_PATH"
ls -lh "$DMG_PATH"
