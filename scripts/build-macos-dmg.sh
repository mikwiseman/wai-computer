#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "$0")/.." && pwd)
PROJECT_PATH="$ROOT_DIR/macos/WaiComputer/WaiComputer.xcodeproj"
SCHEME="WaiComputer"
APP_NAME="WaiComputer"
DMG_VOLUME_NAME=${MACOS_DMG_VOLUME_NAME:-"${APP_NAME} Installer"}
APP_ICON_PATH="$ROOT_DIR/macos/WaiComputer/WaiComputer/Assets.xcassets/AppIcon.appiconset/app_icon_512x512@2x.png"
TEAM_ID=${MACOS_TEAM_ID:-R4A779QVVY}
SIGNING_IDENTITY=${MACOS_SIGNING_IDENTITY:-"Developer ID Application: WaiWai, LLC (R4A779QVVY)"}
RELEASE_ROOT=${MACOS_RELEASE_ROOT:-"$ROOT_DIR/artifacts/releases/macos"}
NOTARY_PROFILE=${NOTARY_KEYCHAIN_PROFILE:-}
NOTARY_KEY=${NOTARY_KEY:-}
NOTARY_KEY_ID=${NOTARY_KEY_ID:-}
NOTARY_ISSUER=${NOTARY_ISSUER:-}
TIMESTAMP=$(date +%Y%m%d-%H%M%S)
TMP_DIR=$(mktemp -d "${TMPDIR:-/tmp}/${APP_NAME}-release.XXXXXX")
ARCHIVE_PATH="$TMP_DIR/${APP_NAME}.xcarchive"
BACKGROUND_PATH="$TMP_DIR/${APP_NAME}-dmg-background.png"
DMG_PATH=""
APP_PATH=""
DMG_ATTACHED=0
DMG_DEVICE=""
DMG_MOUNT_ACTUAL=""
NOTARIZATION_MODE="skipped"
NOTARY_ARGS=()
CUSTOM_BACKGROUND_PATH=${MACOS_DMG_BACKGROUND:-}
REQUIRE_NOTARIZATION=${MACOS_REQUIRE_NOTARIZATION:-0}
REQUIRE_GATEKEEPER=${MACOS_REQUIRE_GATEKEEPER:-0}

if [[ ${MACOS_RELEASE_STRICT:-0} == "1" ]]; then
  REQUIRE_NOTARIZATION=1
  REQUIRE_GATEKEEPER=1
fi

cleanup() {
  detach_sparse_image || true
  rm -rf "$TMP_DIR" >/dev/null 2>&1 || true
}
trap cleanup EXIT

require_tool() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Required tool not found: $1" >&2
    exit 1
  fi
}

build_notary_args() {
  NOTARY_ARGS=()

  if [[ -n "$NOTARY_PROFILE" ]]; then
    NOTARY_ARGS=(--keychain-profile "$NOTARY_PROFILE")
    return 0
  fi

  if [[ -n "$NOTARY_KEY" && -n "$NOTARY_KEY_ID" ]]; then
    NOTARY_ARGS=(--key "$NOTARY_KEY" --key-id "$NOTARY_KEY_ID")
    if [[ -n "$NOTARY_ISSUER" ]]; then
      NOTARY_ARGS+=(--issuer "$NOTARY_ISSUER")
    fi
    return 0
  fi

  return 1
}

notarize_file() {
  local artifact_path=$1
  local artifact_label=$2

  if ! build_notary_args; then
    return 1
  fi

  echo "Submitting ${artifact_label} for notarization..."
  xcrun notarytool submit "$artifact_path" "${NOTARY_ARGS[@]}" --wait
}

gatekeeper_check() {
  local artifact_label=$1
  shift

  if "$@"; then
    return 0
  fi

  if [[ "$REQUIRE_GATEKEEPER" == "1" ]]; then
    echo "Gatekeeper validation failed for ${artifact_label}." >&2
    exit 1
  fi

  echo "Warning: Gatekeeper rejected ${artifact_label}; continuing because MACOS_REQUIRE_GATEKEEPER=0." >&2
}

is_dmg_mounted() {
  mount | grep -Fq " on ${DMG_MOUNT_ACTUAL:-$DMG_MOUNT} "
}

detach_sparse_image() {
  if [[ "$DMG_ATTACHED" != "1" ]]; then
    return 0
  fi

  if ! is_dmg_mounted; then
    DMG_ATTACHED=0
    DMG_DEVICE=""
    DMG_MOUNT_ACTUAL=""
    return 0
  fi

  local target="${DMG_DEVICE:-${DMG_MOUNT_ACTUAL:-$DMG_MOUNT}}"
  local attempt
  for attempt in 1 2 3 4 5; do
    if hdiutil detach "$target" -quiet; then
      break
    fi
    sleep 1
  done

  if is_dmg_mounted; then
    for attempt in 1 2 3 4 5; do
      if hdiutil detach "${DMG_MOUNT_ACTUAL:-$DMG_MOUNT}" -quiet; then
        break
      fi
      sleep 1
    done
  fi

  if is_dmg_mounted; then
    hdiutil detach "$target" -force -quiet || hdiutil detach "${DMG_MOUNT_ACTUAL:-$DMG_MOUNT}" -force -quiet || true
  fi

  for attempt in 1 2 3 4 5; do
    if ! is_dmg_mounted; then
      DMG_ATTACHED=0
      DMG_DEVICE=""
      DMG_MOUNT_ACTUAL=""
      return 0
    fi
    sleep 1
  done

  echo "Failed to detach DMG mount at $DMG_MOUNT" >&2
  return 1
}

require_tool xcodebuild
require_tool codesign
require_tool hdiutil
require_tool ditto
require_tool shasum
require_tool file
require_tool xcrun

mkdir -p "$RELEASE_ROOT"

if [[ -n "$CUSTOM_BACKGROUND_PATH" ]]; then
  "$ROOT_DIR/scripts/render-macos-dmg-background.sh" "$BACKGROUND_PATH" "$APP_ICON_PATH" "$CUSTOM_BACKGROUND_PATH"
else
  "$ROOT_DIR/scripts/render-macos-dmg-background.sh" "$BACKGROUND_PATH" "$APP_ICON_PATH"
fi

echo "Archiving ${APP_NAME} with Developer ID signing..."
xcodebuild archive \
  -project "$PROJECT_PATH" \
  -scheme "$SCHEME" \
  -configuration Release \
  -destination 'generic/platform=macOS' \
  -archivePath "$ARCHIVE_PATH" \
  DEVELOPMENT_TEAM="$TEAM_ID" \
  CODE_SIGN_STYLE=Manual \
  CODE_SIGN_IDENTITY="$SIGNING_IDENTITY" \
  ENABLE_HARDENED_RUNTIME=YES \
  OTHER_CODE_SIGN_FLAGS='--timestamp' \
  ARCHS='arm64 x86_64' \
  ONLY_ACTIVE_ARCH=NO

APP_PATH="$ARCHIVE_PATH/Products/Applications/${APP_NAME}.app"
if [[ ! -d "$APP_PATH" ]]; then
  echo "Archived app not found at $APP_PATH" >&2
  exit 1
fi

APP_INFO="$APP_PATH/Contents/Info.plist"
VERSION=$(/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' "$APP_INFO")
BUILD=$(/usr/libexec/PlistBuddy -c 'Print :CFBundleVersion' "$APP_INFO")
RELEASE_DIR="$RELEASE_ROOT/${VERSION}-${BUILD}"
mkdir -p "$RELEASE_DIR"

APP_BINARY="$APP_PATH/Contents/MacOS/${APP_NAME}"
UNIVERSAL_INFO=$(file "$APP_BINARY")
echo "$UNIVERSAL_INFO"

codesign --verify --deep --strict --verbose=2 "$APP_PATH"

if build_notary_args; then
  APP_ZIP="$TMP_DIR/${APP_NAME}.zip"
  ditto -c -k --sequesterRsrc --keepParent "$APP_PATH" "$APP_ZIP"
  notarize_file "$APP_ZIP" "app bundle archive"
  xcrun stapler staple "$APP_PATH"
  xcrun stapler validate "$APP_PATH"
  NOTARIZATION_MODE="app-and-dmg"
elif [[ "$REQUIRE_NOTARIZATION" == "1" ]]; then
  echo "Notarization is required but credentials are missing. Set NOTARY_KEYCHAIN_PROFILE or NOTARY_KEY + NOTARY_KEY_ID [+ NOTARY_ISSUER]." >&2
  exit 1
else
  echo "Skipping notarization: set NOTARY_KEYCHAIN_PROFILE or NOTARY_KEY + NOTARY_KEY_ID [+ NOTARY_ISSUER]."
fi

gatekeeper_check "app bundle" spctl -a -vv --type execute "$APP_PATH"

DMG_PATH="$RELEASE_DIR/${APP_NAME}-${VERSION}-${BUILD}.dmg"
SPARSE_PATH="$TMP_DIR/${APP_NAME}.sparseimage"
DMG_MOUNT="$TMP_DIR/dmg-mount"
rm -f "$DMG_PATH" "$SPARSE_PATH"

echo "Creating sparse image..."
hdiutil create -size 200m -fs HFS+ -volname "$DMG_VOLUME_NAME" -type SPARSE "$SPARSE_PATH"

echo "Mounting sparse image to custom mount point..."
mkdir -p "$DMG_MOUNT"
ATTACH_OUTPUT=$(hdiutil attach "$SPARSE_PATH" -mountpoint "$DMG_MOUNT" -nobrowse -noverify)
printf '%s\n' "$ATTACH_OUTPUT"
DMG_ATTACHED=1
DMG_DEVICE=$(printf '%s\n' "$ATTACH_OUTPUT" | awk 'END {print $1}')
DMG_MOUNT_ACTUAL=$(printf '%s\n' "$ATTACH_OUTPUT" | awk 'END {print $NF}')
if [[ -z "$DMG_DEVICE" ]]; then
  echo "Warning: unable to determine mounted DMG device for $DMG_MOUNT; falling back to mountpoint detach." >&2
fi

echo "Copying app payload..."
ditto "$APP_PATH" "$DMG_MOUNT/${APP_NAME}.app"
ln -s /Applications "$DMG_MOUNT/Applications"

sync

echo "Detaching sparse image..."
detach_sparse_image

echo "Converting to compressed DMG..."
hdiutil convert "$SPARSE_PATH" -format UDZO -o "$DMG_PATH" -quiet

echo "Signing DMG..."
codesign --sign "$SIGNING_IDENTITY" --timestamp "$DMG_PATH"

if [[ ! -f "$DMG_PATH" ]]; then
  echo "DMG creation did not produce $DMG_PATH" >&2
  exit 1
fi

codesign --verify --verbose=2 "$DMG_PATH"
hdiutil verify "$DMG_PATH"

if [[ "$NOTARIZATION_MODE" != "skipped" ]]; then
  notarize_file "$DMG_PATH" "disk image"
  xcrun stapler staple "$DMG_PATH"
  xcrun stapler validate "$DMG_PATH"
elif [[ "$REQUIRE_NOTARIZATION" == "1" ]]; then
  echo "Notarization is required but the DMG was not submitted." >&2
  exit 1
else
  echo "DMG created without notarization."
fi

gatekeeper_check "disk image" spctl --assess --type open --context context:primary-signature -vv "$DMG_PATH"

cp "$BACKGROUND_PATH" "$RELEASE_DIR/${APP_NAME}-installer-background.png"
shasum -a 256 "$DMG_PATH" > "$RELEASE_DIR/${APP_NAME}-${VERSION}-${BUILD}.dmg.sha256"
cp "$DMG_PATH" "$RELEASE_ROOT/${APP_NAME}-latest.dmg"
cp "$RELEASE_DIR/${APP_NAME}-${VERSION}-${BUILD}.dmg.sha256" "$RELEASE_ROOT/${APP_NAME}-latest.dmg.sha256"
cat > "$RELEASE_DIR/release-metadata.txt" <<META
app=${APP_NAME}
version=${VERSION}
build=${BUILD}
team_id=${TEAM_ID}
signing_identity=${SIGNING_IDENTITY}
notarization=${NOTARIZATION_MODE}
notarization_required=${REQUIRE_NOTARIZATION}
gatekeeper_required=${REQUIRE_GATEKEEPER}
archive=${ARCHIVE_PATH}
dmg=${DMG_PATH}
built_at=${TIMESTAMP}
META

echo
printf 'DMG ready: %s\n' "$DMG_PATH"
printf 'Checksum: %s\n' "$RELEASE_DIR/${APP_NAME}-${VERSION}-${BUILD}.dmg.sha256"
printf 'Background: %s\n' "$RELEASE_DIR/${APP_NAME}-installer-background.png"
printf 'Metadata: %s\n' "$RELEASE_DIR/release-metadata.txt"
