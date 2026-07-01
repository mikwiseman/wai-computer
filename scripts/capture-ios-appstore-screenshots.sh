#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DERIVED_DATA="${DERIVED_DATA:-$ROOT_DIR/build/screenshots}"
RAW_DIR="$ROOT_DIR/build/screenshots/raw"
APPSTORE_DIR="$ROOT_DIR/fastlane/screenshots/en-US"
APP_PATH="$DERIVED_DATA/Build/Products/Debug-iphonesimulator/WaiComputer.app"
BUNDLE_ID=""
IPHONE_DEVICE="${IPHONE_DEVICE:-iPhone 17 Pro Max}"
IPAD_DEVICE="${IPAD_DEVICE:-iPad Pro 13-inch (M5)}"

device_udid() {
  local device_name="$1"

  python3 - "$device_name" <<'PY'
import json
import subprocess
import sys

device_name = sys.argv[1]
payload = json.loads(
    subprocess.check_output(
        ["xcrun", "simctl", "list", "devices", "available", "-j"],
        text=True,
    )
)

for devices in payload.get("devices", {}).values():
    for device in devices:
        if device.get("name") == device_name and device.get("isAvailable", True):
            print(device["udid"])
            raise SystemExit(0)

raise SystemExit(f"Unable to find simulator named: {device_name}")
PY
}

build_app() {
  xcodebuild \
    -project "$ROOT_DIR/ios/WaiComputer/WaiComputeriOS.xcodeproj" \
    -scheme WaiComputer \
    -configuration Debug \
    -sdk iphonesimulator \
    -derivedDataPath "$DERIVED_DATA" \
    build
}

boot_and_prepare_device() {
  local udid="$1"

  xcrun simctl boot "$udid" >/dev/null 2>&1 || true
  xcrun simctl bootstatus "$udid" -b
  xcrun simctl ui "$udid" appearance dark >/dev/null 2>&1 || true
  xcrun simctl status_bar "$udid" clear >/dev/null 2>&1 || true
  xcrun simctl status_bar "$udid" override \
    --time 9:41 \
    --dataNetwork wifi \
    --wifiBars 3 \
    --batteryState charged \
    --batteryLevel 100 >/dev/null 2>&1 || true
}

install_app() {
  local udid="$1"

  xcrun simctl uninstall "$udid" "$BUNDLE_ID" >/dev/null 2>&1 || true
  xcrun simctl install "$udid" "$APP_PATH"
}

read_bundle_id() {
  /usr/libexec/PlistBuddy -c "Print :CFBundleIdentifier" "$APP_PATH/Info.plist"
}

launch_for_capture() {
  local udid="$1"
  local screen="$2"
  local tab="${3:-}"
  local recording_id="${4:-}"
  local detail_tab="${5:-}"
  local -a env_vars=(
    "SIMCTL_CHILD_WAI_ENABLE_SCREENSHOT_MODE=1"
    "SIMCTL_CHILD_WAI_SCREENSHOT_SCREEN=$screen"
  )

  if [[ -n "$tab" ]]; then
    env_vars+=("SIMCTL_CHILD_WAICOMPUTER_TAB=$tab")
  fi
  if [[ -n "$recording_id" ]]; then
    env_vars+=("SIMCTL_CHILD_WAICOMPUTER_RECORDING_ID=$recording_id")
  fi
  if [[ -n "$detail_tab" ]]; then
    env_vars+=("SIMCTL_CHILD_WAICOMPUTER_DETAIL_TAB=$detail_tab")
  fi

  xcrun simctl terminate "$udid" "$BUNDLE_ID" >/dev/null 2>&1 || true
  env "${env_vars[@]}" xcrun simctl launch --terminate-running-process "$udid" "$BUNDLE_ID" >/dev/null
  sleep 2
}

capture_screen() {
  local udid="$1"
  local output_name="$2"
  local screen="$3"
  local tab="${4:-}"
  local recording_id="${5:-}"
  local detail_tab="${6:-}"

  launch_for_capture "$udid" "$screen" "$tab" "$recording_id" "$detail_tab"
  xcrun simctl io "$udid" screenshot "$RAW_DIR/$output_name"
}

sync_to_fastlane() {
  cp "$RAW_DIR/01_record_phone.png" "$APPSTORE_DIR/01_record_framed.png"
  cp "$RAW_DIR/02_library_phone.png" "$APPSTORE_DIR/02_library_framed.png"
  cp "$RAW_DIR/03_detail_phone.png" "$APPSTORE_DIR/03_detail_framed.png"
  cp "$RAW_DIR/04_settings_phone.png" "$APPSTORE_DIR/04_settings_framed.png"

  cp "$RAW_DIR/01_record_ipad.png" "$APPSTORE_DIR/01_record_ipad_framed.png"
  cp "$RAW_DIR/02_library_ipad.png" "$APPSTORE_DIR/02_library_ipad_framed.png"
  cp "$RAW_DIR/03_detail_ipad.png" "$APPSTORE_DIR/03_detail_ipad_framed.png"
  cp "$RAW_DIR/04_settings_ipad.png" "$APPSTORE_DIR/04_settings_ipad_framed.png"
}

main() {
  mkdir -p "$RAW_DIR" "$APPSTORE_DIR"

  build_app

  if [[ ! -d "$APP_PATH" ]]; then
    echo "Built app not found at $APP_PATH" >&2
    exit 1
  fi

  BUNDLE_ID="$(read_bundle_id)"
  if [[ -z "$BUNDLE_ID" ]]; then
    echo "Unable to determine bundle identifier from $APP_PATH" >&2
    exit 1
  fi

  local iphone_udid
  local ipad_udid
  iphone_udid="$(device_udid "$IPHONE_DEVICE")"
  ipad_udid="$(device_udid "$IPAD_DEVICE")"

  boot_and_prepare_device "$iphone_udid"
  boot_and_prepare_device "$ipad_udid"
  install_app "$iphone_udid"
  install_app "$ipad_udid"

  capture_screen "$iphone_udid" "01_record_phone.png" "record" "0"
  capture_screen "$iphone_udid" "02_library_phone.png" "library" "1"
  capture_screen "$iphone_udid" "03_detail_phone.png" "detail" "" "rec-1" "transcript"
  capture_screen "$iphone_udid" "04_settings_phone.png" "settings" "3"

  capture_screen "$ipad_udid" "01_record_ipad.png" "record" "0"
  capture_screen "$ipad_udid" "02_library_ipad.png" "library" "1"
  capture_screen "$ipad_udid" "03_detail_ipad.png" "detail" "" "rec-1" "transcript"
  capture_screen "$ipad_udid" "04_settings_ipad.png" "settings" "3"

  sync_to_fastlane

  echo "Updated raw screenshots in: $RAW_DIR"
  echo "Updated App Store screenshots in: $APPSTORE_DIR"
}

main "$@"
