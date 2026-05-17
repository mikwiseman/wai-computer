#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "$0")/.." && pwd)
PROJECT_PATH="$ROOT_DIR/macos/WaiComputer/WaiComputer.xcodeproj"
SCHEME=${MACOS_SCHEME:-WaiComputer}
CONFIGURATION=${MACOS_CONFIGURATION:-Release}
APP_NAME="WaiComputer"
DMG_VOLUME_NAME=${MACOS_DMG_VOLUME_NAME:-"${APP_NAME} Installer"}
APP_ICON_PATH="$ROOT_DIR/macos/WaiComputer/WaiComputer/Assets.xcassets/AppIcon.appiconset/app_icon_512x512@2x.png"
TEAM_ID=${MACOS_TEAM_ID:-<apple-team-id>}
SIGNING_IDENTITY=${MACOS_SIGNING_IDENTITY:-"Developer ID Application: WaiWai, LLC (<apple-team-id>)"}
RELEASE_ROOT=${MACOS_RELEASE_ROOT:-"$ROOT_DIR/artifacts/releases/macos"}
SPARKLE_DOWNLOAD_BASE_URL=${MACOS_SPARKLE_DOWNLOAD_BASE_URL:-"https://wai.computer/releases/macos"}
SPARKLE_FEED_URL=${MACOS_SPARKLE_FEED_URL:-"${SPARKLE_DOWNLOAD_BASE_URL}/appcast.xml"}
SPARKLE_KEYCHAIN_ACCOUNT=${SPARKLE_KEYCHAIN_ACCOUNT:-is.waiwai.computer.sparkle}
SPARKLE_PRIVATE_KEY=${SPARKLE_PRIVATE_KEY:-}
SPARKLE_PRIVATE_KEY_FILE=${SPARKLE_PRIVATE_KEY_FILE:-}
SPARKLE_SIGN_UPDATE_BIN=${SPARKLE_SIGN_UPDATE_BIN:-}
APPSTORECONNECT_CONFIG=${APPSTORECONNECT_CONFIG:-"$APPSTORECONNECT_CONFIG"}
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
DMGBUILD_BIN="${DMGBUILD_BIN:-}"
NOTARIZATION_MODE="skipped"
NOTARY_ARGS=()
CUSTOM_BACKGROUND_PATH=${MACOS_DMG_BACKGROUND:-}
REQUIRE_NOTARIZATION=${MACOS_REQUIRE_NOTARIZATION:-0}
REQUIRE_GATEKEEPER=${MACOS_REQUIRE_GATEKEEPER:-0}
REQUIRE_SPARKLE_SIGNATURE=${MACOS_REQUIRE_SPARKLE_SIGNATURE:-0}
RELEASE_CHANNEL=${RELEASE_CHANNEL:-stable}
case "$RELEASE_CHANNEL" in
  stable|beta) ;;
  *) echo "ERROR: RELEASE_CHANNEL must be 'stable' or 'beta', got '$RELEASE_CHANNEL'" >&2; exit 1 ;;
esac

if [[ ${MACOS_RELEASE_STRICT:-0} == "1" ]]; then
  REQUIRE_NOTARIZATION=1
  REQUIRE_GATEKEEPER=1
  REQUIRE_SPARKLE_SIGNATURE=1
fi

if [[ "$SCHEME" != "WaiComputer" && "${MACOS_ALLOW_NON_DEFAULT_SCHEME:-0}" != "1" ]]; then
  cat >&2 <<EOF
ERROR: macOS DMG releases must build the WaiComputer scheme, got "$SCHEME".

Set MACOS_SCHEME=WaiComputer, or set MACOS_ALLOW_NON_DEFAULT_SCHEME=1 only for
an intentional local experiment that must not be published.
EOF
  exit 1
fi

cleanup() {
  rm -rf "$TMP_DIR" >/dev/null 2>&1 || true
}
trap cleanup EXIT

ensure_dmgbuild() {
  if [[ -n "${DMGBUILD_BIN:-}" && -x "$DMGBUILD_BIN" ]]; then
    return 0
  fi

  local candidate
  for candidate in "$HOME/Library/Python/3.14/bin/dmgbuild" "$HOME/Library/Python/3.13/bin/dmgbuild" "$HOME/Library/Python/3.12/bin/dmgbuild" "$HOME/Library/Python/3.11/bin/dmgbuild"; do
    if [[ -x "$candidate" ]]; then
      DMGBUILD_BIN="$candidate"
      return 0
    fi
  done

  if command -v dmgbuild >/dev/null 2>&1; then
    DMGBUILD_BIN=$(command -v dmgbuild)
    return 0
  fi

  echo "Installing dmgbuild via pip..."
  python3 -m pip install --user --quiet --break-system-packages dmgbuild >&2
  for candidate in "$HOME/Library/Python/3.14/bin/dmgbuild" "$HOME/Library/Python/3.13/bin/dmgbuild" "$HOME/Library/Python/3.12/bin/dmgbuild" "$HOME/Library/Python/3.11/bin/dmgbuild"; do
    if [[ -x "$candidate" ]]; then
      DMGBUILD_BIN="$candidate"
      return 0
    fi
  done

  if command -v dmgbuild >/dev/null 2>&1; then
    DMGBUILD_BIN=$(command -v dmgbuild)
    return 0
  fi

  echo "dmgbuild not found after pip install; install it manually." >&2
  exit 1
}

require_tool() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Required tool not found: $1" >&2
    exit 1
  fi
}

expand_user_path() {
  case "$1" in
    "~")
      printf '%s\n' "$HOME"
      ;;
    "~/"*)
      printf '%s\n' "$HOME/${1#"~/"}"
      ;;
    *)
      printf '%s\n' "$1"
      ;;
  esac
}

read_appstoreconnect_config_value() {
  if [[ ! -f "$APPSTORECONNECT_CONFIG" ]]; then
    return 0
  fi

  /usr/bin/plutil -extract "$1" raw -o - "$APPSTORECONNECT_CONFIG" 2>/dev/null || true
}

load_notary_defaults_from_appstoreconnect_config() {
  if [[ -n "$NOTARY_PROFILE" || -n "$NOTARY_KEY" || -n "$NOTARY_KEY_ID" ]]; then
    return 0
  fi

  if [[ ! -f "$APPSTORECONNECT_CONFIG" ]]; then
    return 0
  fi

  local config_key config_key_id config_issuer
  config_key=$(read_appstoreconnect_config_value key_filepath)
  config_key_id=$(read_appstoreconnect_config_value key_id)
  config_issuer=$(read_appstoreconnect_config_value issuer_id)

  if [[ -n "$config_key" && -n "$config_key_id" ]]; then
    NOTARY_KEY=$(expand_user_path "$config_key")
    NOTARY_KEY_ID="$config_key_id"
    if [[ -n "$config_issuer" ]]; then
      NOTARY_ISSUER="$config_issuer"
    fi
  fi
}

build_notary_args() {
  NOTARY_ARGS=()

  if [[ -n "$NOTARY_PROFILE" ]]; then
    NOTARY_ARGS=(--keychain-profile "$NOTARY_PROFILE")
    return 0
  fi

  if [[ -n "$NOTARY_KEY" && -n "$NOTARY_KEY_ID" ]]; then
    if [[ ! -f "$NOTARY_KEY" ]]; then
      echo "Notary API key file not found: $NOTARY_KEY" >&2
      return 1
    fi
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
  local notary_output status submission_id

  if ! build_notary_args; then
    return 1
  fi

  echo "Submitting ${artifact_label} for notarization..."
  notary_output=$(xcrun notarytool submit "$artifact_path" "${NOTARY_ARGS[@]}" --wait --output-format json)
  printf '%s\n' "$notary_output"

  status=$(printf '%s' "$notary_output" | /usr/bin/plutil -extract status raw -o - - 2>/dev/null || true)
  submission_id=$(printf '%s' "$notary_output" | /usr/bin/plutil -extract id raw -o - - 2>/dev/null || true)
  if [[ "$status" != "Accepted" ]]; then
    echo "Notarization failed for ${artifact_label}: status ${status:-unknown}, id ${submission_id:-unknown}." >&2
    if [[ -n "$submission_id" ]]; then
      xcrun notarytool log "$submission_id" "${NOTARY_ARGS[@]}" || true
    fi
    return 1
  fi
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

sign_bundle_if_present() {
  local bundle_path=$1
  shift

  if [[ ! -e "$bundle_path" ]]; then
    return 0
  fi

  codesign --force --sign "$SIGNING_IDENTITY" --timestamp --options runtime "$@" "$bundle_path"
  codesign --verify --strict --verbose=2 "$bundle_path"
}

resign_sparkle_for_distribution() {
  local sparkle_framework="$APP_PATH/Contents/Frameworks/Sparkle.framework"
  local sparkle_version_dir current_version

  if [[ ! -d "$sparkle_framework" ]]; then
    return 0
  fi

  current_version=$(readlink "$sparkle_framework/Versions/Current" 2>/dev/null || true)
  if [[ -n "$current_version" && -d "$sparkle_framework/Versions/$current_version" ]]; then
    sparkle_version_dir="$sparkle_framework/Versions/$current_version"
  else
    sparkle_version_dir="$sparkle_framework/Versions/Current"
  fi

  if [[ ! -d "$sparkle_version_dir" ]]; then
    echo "Sparkle framework version directory not found under $sparkle_framework" >&2
    exit 1
  fi

  echo "Re-signing Sparkle nested code for Developer ID distribution..."
  sign_bundle_if_present "$sparkle_version_dir/XPCServices/Installer.xpc" --preserve-metadata=identifier,entitlements
  sign_bundle_if_present "$sparkle_version_dir/XPCServices/Downloader.xpc" --preserve-metadata=identifier,entitlements
  sign_bundle_if_present "$sparkle_version_dir/Autoupdate"
  sign_bundle_if_present "$sparkle_version_dir/Updater.app"
  sign_bundle_if_present "$sparkle_framework"
}

require_tool xcodebuild
require_tool codesign
require_tool hdiutil
require_tool ditto
require_tool shasum
require_tool file
require_tool xcrun
require_tool python3

load_notary_defaults_from_appstoreconnect_config

find_sign_update_bin() {
  if [[ -n "$SPARKLE_SIGN_UPDATE_BIN" ]]; then
    if [[ -x "$SPARKLE_SIGN_UPDATE_BIN" ]]; then
      printf '%s\n' "$SPARKLE_SIGN_UPDATE_BIN"
      return 0
    fi
    echo "Configured SPARKLE_SIGN_UPDATE_BIN is not executable: $SPARKLE_SIGN_UPDATE_BIN" >&2
    return 1
  fi

  local candidate
  candidate=$(find "$HOME/Library/Developer/Xcode/DerivedData" -path '*/SourcePackages/artifacts/sparkle/Sparkle/bin/sign_update' -type f -perm -111 2>/dev/null | head -n 1 || true)
  if [[ -n "$candidate" ]]; then
    printf '%s\n' "$candidate"
    return 0
  fi

  echo "Sparkle sign_update not found. Build or resolve the WaiComputer scheme first, or set SPARKLE_SIGN_UPDATE_BIN." >&2
  return 1
}

sign_sparkle_update() {
  local artifact_path=$1
  local sign_update_bin=$2

  if [[ -n "$SPARKLE_PRIVATE_KEY" ]]; then
    printf '%s' "$SPARKLE_PRIVATE_KEY" | "$sign_update_bin" --ed-key-file - "$artifact_path"
    return $?
  fi

  if [[ -n "$SPARKLE_PRIVATE_KEY_FILE" ]]; then
    "$sign_update_bin" --ed-key-file "$SPARKLE_PRIVATE_KEY_FILE" "$artifact_path"
    return $?
  fi

  "$sign_update_bin" --account "$SPARKLE_KEYCHAIN_ACCOUNT" "$artifact_path"
}

render_dmgbuild_settings() {
  cat <<'PY'
import os

volume_name = os.environ["DMG_VOLUME_NAME"]
app_path = os.environ["APP_PATH"]
app_name = os.environ["APP_NAME"]
background = os.environ["BACKGROUND_PATH"]

format = "ULFO"
size = "200M"
files = [app_path]
symlinks = {"Applications": "/Applications"}
icon_locations = {
    f"{app_name}.app": (190, 190),
    "Applications": (480, 190),
}
window_rect = ((100, 100), (640, 320))
default_view = "icon-view"
show_status_bar = False
show_tab_view = False
show_toolbar = False
show_pathbar = False
show_sidebar = False
icon_size = 96
text_size = 12
include_icon_view_settings = "auto"
include_list_view_settings = "auto"
PY
}

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
  -configuration "$CONFIGURATION" \
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
RELEASE_SLUG="${VERSION}-${BUILD}"
if [[ "$RELEASE_CHANNEL" != "stable" ]]; then
  RELEASE_SLUG="${VERSION}-${BUILD}-${RELEASE_CHANNEL}"
fi
RELEASE_DIR="$RELEASE_ROOT/${RELEASE_SLUG}"
mkdir -p "$RELEASE_DIR"

APP_BINARY="$APP_PATH/Contents/MacOS/${APP_NAME}"
UNIVERSAL_INFO=$(file "$APP_BINARY")
echo "$UNIVERSAL_INFO"

resign_sparkle_for_distribution
codesign --verify --deep --strict --verbose=2 "$APP_PATH"

if build_notary_args; then
  APP_ZIP="$TMP_DIR/${APP_NAME}.zip"
  ditto -c -k --sequesterRsrc --keepParent "$APP_PATH" "$APP_ZIP"
  notarize_file "$APP_ZIP" "app bundle archive"
  xcrun stapler staple "$APP_PATH"
  xcrun stapler validate "$APP_PATH"
  NOTARIZATION_MODE="app-and-dmg"
elif [[ "$REQUIRE_NOTARIZATION" == "1" ]]; then
  echo "Notarization is required but credentials are missing. Set NOTARY_KEYCHAIN_PROFILE, NOTARY_KEY + NOTARY_KEY_ID [+ NOTARY_ISSUER], or APPSTORECONNECT_CONFIG." >&2
  exit 1
else
  echo "Skipping notarization: set NOTARY_KEYCHAIN_PROFILE, NOTARY_KEY + NOTARY_KEY_ID [+ NOTARY_ISSUER], or APPSTORECONNECT_CONFIG."
fi

gatekeeper_check "app bundle" spctl -a -vv --type execute "$APP_PATH"

DMG_PATH="$RELEASE_DIR/${APP_NAME}-${VERSION}-${BUILD}.dmg"
rm -f "$DMG_PATH"

ensure_dmgbuild
DMG_SETTINGS="$TMP_DIR/dmgbuild-settings.py"
render_dmgbuild_settings > "$DMG_SETTINGS"

echo "Building DMG with dmgbuild..."
DMG_VOLUME_NAME="$DMG_VOLUME_NAME" \
APP_PATH="$APP_PATH" \
APP_NAME="$APP_NAME" \
BACKGROUND_PATH="$BACKGROUND_PATH" \
"$DMGBUILD_BIN" -s "$DMG_SETTINGS" "$DMG_VOLUME_NAME" "$DMG_PATH"

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
RELEASE_NOTES_PATH="$RELEASE_DIR/release-notes.md"
generate_release_notes() {
  echo "# ${APP_NAME} ${VERSION} (${BUILD})"
  echo
  local prev_build prev_commit notes
  prev_build=$((BUILD - 1))
  prev_commit=""
  if [[ "$prev_build" -gt 0 ]]; then
    prev_commit=$(git log -S "CURRENT_PROJECT_VERSION: \"${prev_build}\"" --pretty=format:"%H" -- macos/WaiComputer/project.yml 2>/dev/null | head -1 || true)
  fi
  notes=""
  if [[ -n "$prev_commit" ]]; then
    notes=$(git log --no-merges --pretty=format:"%s" "${prev_commit}..HEAD" -- macos/ shared/ scripts/build-macos-dmg.sh 2>/dev/null \
      | grep -vE "^(chore|docs|test|refactor|wip)[\(:]" \
      | sed -E 's/^macOS [0-9]+\.[0-9]+\.[0-9]+,? build [0-9]+ (— )?//' \
      | sed -E 's/^/- /' \
      | head -25 || true)
  fi
  if [[ -z "${notes:-}" ]]; then
    notes=$(git log -1 --pretty=format:"%s" 2>/dev/null \
      | sed -E 's/^macOS [0-9]+\.[0-9]+\.[0-9]+,? build [0-9]+ (— )?//' \
      | sed -E 's/^/- /' || echo "- Build ${BUILD}")
  fi
  echo "$notes"
}
generate_release_notes > "$RELEASE_NOTES_PATH"

DOWNLOAD_URL="${SPARKLE_DOWNLOAD_BASE_URL}/${RELEASE_SLUG}/${APP_NAME}-${VERSION}-${BUILD}.dmg"
RELEASE_NOTES_URL="${SPARKLE_DOWNLOAD_BASE_URL}/${RELEASE_SLUG}/release-notes.md"
PUBLISHED_AT=$(date -u '+%a, %d %b %Y %H:%M:%S %z')
SPARKLE_SIGNATURE=""
if SIGN_UPDATE_BIN=$(find_sign_update_bin); then
  if SPARKLE_SIGNATURE=$(sign_sparkle_update "$DMG_PATH" "$SIGN_UPDATE_BIN"); then
    SPARKLE_SIGNATURE=$(printf '%s' "$SPARKLE_SIGNATURE" | tr -d '\n')
  else
    SPARKLE_SIGNATURE=""
    echo "Warning: Sparkle sign_update failed; appcast will not contain an EdDSA signature." >&2
  fi
fi

if [[ -z "$SPARKLE_SIGNATURE" && "$REQUIRE_SPARKLE_SIGNATURE" == "1" ]]; then
  echo "Sparkle EdDSA signature is required. Set SPARKLE_PRIVATE_KEY, SPARKLE_PRIVATE_KEY_FILE, or keychain account ${SPARKLE_KEYCHAIN_ACCOUNT}." >&2
  exit 1
fi

DMG_BYTES=$(stat -f '%z' "$DMG_PATH")
SPARKLE_ENCLOSURE_ATTRS=${SPARKLE_SIGNATURE:-"length=\"${DMG_BYTES}\""}
CHANNEL_XML=""
if [[ "$RELEASE_CHANNEL" == "beta" ]]; then
  CHANNEL_XML=$'      <sparkle:channel>beta</sparkle:channel>\n'
fi
APPCAST_PATH="$RELEASE_ROOT/appcast.xml"
cat > "$APPCAST_PATH" <<XML
<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:sparkle="http://www.andymatuschak.org/xml-namespaces/sparkle">
  <channel>
    <title>${APP_NAME}</title>
    <link>${SPARKLE_FEED_URL}</link>
    <description>Auto-update feed for ${APP_NAME} direct-download macOS releases.</description>
    <language>en</language>
    <item>
      <title>${APP_NAME} ${VERSION}</title>
      <pubDate>${PUBLISHED_AT}</pubDate>
${CHANNEL_XML}      <sparkle:version>${BUILD}</sparkle:version>
      <sparkle:shortVersionString>${VERSION}</sparkle:shortVersionString>
      <sparkle:minimumSystemVersion>14.0</sparkle:minimumSystemVersion>
      <sparkle:releaseNotesLink>${RELEASE_NOTES_URL}</sparkle:releaseNotesLink>
      <enclosure url="${DOWNLOAD_URL}" type="application/x-apple-diskimage" ${SPARKLE_ENCLOSURE_ATTRS}/>
    </item>
  </channel>
</rss>
XML
cp "$APPCAST_PATH" "$RELEASE_DIR/appcast.xml"
cp "$RELEASE_NOTES_PATH" "$RELEASE_ROOT/release-notes.md"
cat > "$RELEASE_DIR/release-metadata.txt" <<META
app=${APP_NAME}
version=${VERSION}
build=${BUILD}
release_slug=${RELEASE_SLUG}
release_channel=${RELEASE_CHANNEL}
team_id=${TEAM_ID}
signing_identity=${SIGNING_IDENTITY}
notarization=${NOTARIZATION_MODE}
notarization_required=${REQUIRE_NOTARIZATION}
gatekeeper_required=${REQUIRE_GATEKEEPER}
archive=${ARCHIVE_PATH}
dmg=${DMG_PATH}
appcast=${APPCAST_PATH}
sparkle_feed_url=${SPARKLE_FEED_URL}
sparkle_download_url=${DOWNLOAD_URL}
sparkle_signed=$([[ -n "$SPARKLE_SIGNATURE" ]] && printf yes || printf no)
built_at=${TIMESTAMP}
META
cp "$RELEASE_DIR/release-metadata.txt" "$RELEASE_ROOT/latest-release-metadata.txt"

echo
printf 'DMG ready: %s\n' "$DMG_PATH"
printf 'Checksum: %s\n' "$RELEASE_DIR/${APP_NAME}-${VERSION}-${BUILD}.dmg.sha256"
printf 'Appcast: %s\n' "$APPCAST_PATH"
printf 'Background: %s\n' "$RELEASE_DIR/${APP_NAME}-installer-background.png"
printf 'Metadata: %s\n' "$RELEASE_DIR/release-metadata.txt"
