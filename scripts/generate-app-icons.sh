#!/bin/bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SOURCE_ICON="${1:-$ROOT_DIR/assets/app-icon-1024.png}"

if [[ ! -f "$SOURCE_ICON" ]]; then
  echo "Source icon not found: $SOURCE_ICON" >&2
  exit 1
fi

generate_png() {
  local size="$1"
  local destination="$2"
  mkdir -p "$(dirname "$destination")"
  sips -z "$size" "$size" "$SOURCE_ICON" --out "$destination" >/dev/null
}

echo "Generating iOS app icons from $SOURCE_ICON"
generate_png 40 "$ROOT_DIR/ios/WaiSay/WaiSay/Assets.xcassets/AppIcon.appiconset/icon-20@2x.png"
generate_png 60 "$ROOT_DIR/ios/WaiSay/WaiSay/Assets.xcassets/AppIcon.appiconset/icon-20@3x.png"
generate_png 58 "$ROOT_DIR/ios/WaiSay/WaiSay/Assets.xcassets/AppIcon.appiconset/icon-29@2x.png"
generate_png 87 "$ROOT_DIR/ios/WaiSay/WaiSay/Assets.xcassets/AppIcon.appiconset/icon-29@3x.png"
generate_png 80 "$ROOT_DIR/ios/WaiSay/WaiSay/Assets.xcassets/AppIcon.appiconset/icon-40@2x.png"
generate_png 120 "$ROOT_DIR/ios/WaiSay/WaiSay/Assets.xcassets/AppIcon.appiconset/icon-40@3x.png"
generate_png 120 "$ROOT_DIR/ios/WaiSay/WaiSay/Assets.xcassets/AppIcon.appiconset/icon-60@2x.png"
generate_png 180 "$ROOT_DIR/ios/WaiSay/WaiSay/Assets.xcassets/AppIcon.appiconset/icon-60@3x.png"
generate_png 20 "$ROOT_DIR/ios/WaiSay/WaiSay/Assets.xcassets/AppIcon.appiconset/icon-20@1x-ipad.png"
generate_png 40 "$ROOT_DIR/ios/WaiSay/WaiSay/Assets.xcassets/AppIcon.appiconset/icon-20@2x-ipad.png"
generate_png 29 "$ROOT_DIR/ios/WaiSay/WaiSay/Assets.xcassets/AppIcon.appiconset/icon-29@1x-ipad.png"
generate_png 58 "$ROOT_DIR/ios/WaiSay/WaiSay/Assets.xcassets/AppIcon.appiconset/icon-29@2x-ipad.png"
generate_png 40 "$ROOT_DIR/ios/WaiSay/WaiSay/Assets.xcassets/AppIcon.appiconset/icon-40@1x-ipad.png"
generate_png 80 "$ROOT_DIR/ios/WaiSay/WaiSay/Assets.xcassets/AppIcon.appiconset/icon-40@2x-ipad.png"
generate_png 76 "$ROOT_DIR/ios/WaiSay/WaiSay/Assets.xcassets/AppIcon.appiconset/icon-76@1x.png"
generate_png 152 "$ROOT_DIR/ios/WaiSay/WaiSay/Assets.xcassets/AppIcon.appiconset/icon-76@2x.png"
generate_png 167 "$ROOT_DIR/ios/WaiSay/WaiSay/Assets.xcassets/AppIcon.appiconset/icon-83.5@2x.png"
generate_png 1024 "$ROOT_DIR/ios/WaiSay/WaiSay/Assets.xcassets/AppIcon.appiconset/icon-1024.png"

echo "Generating macOS app icons"
generate_png 16 "$ROOT_DIR/macos/WaiSay/WaiSay/Assets.xcassets/AppIcon.appiconset/app_icon_16x16.png"
generate_png 32 "$ROOT_DIR/macos/WaiSay/WaiSay/Assets.xcassets/AppIcon.appiconset/app_icon_16x16@2x.png"
generate_png 32 "$ROOT_DIR/macos/WaiSay/WaiSay/Assets.xcassets/AppIcon.appiconset/app_icon_32x32.png"
generate_png 64 "$ROOT_DIR/macos/WaiSay/WaiSay/Assets.xcassets/AppIcon.appiconset/app_icon_32x32@2x.png"
generate_png 128 "$ROOT_DIR/macos/WaiSay/WaiSay/Assets.xcassets/AppIcon.appiconset/app_icon_128x128.png"
generate_png 256 "$ROOT_DIR/macos/WaiSay/WaiSay/Assets.xcassets/AppIcon.appiconset/app_icon_128x128@2x.png"
generate_png 256 "$ROOT_DIR/macos/WaiSay/WaiSay/Assets.xcassets/AppIcon.appiconset/app_icon_256x256.png"
generate_png 512 "$ROOT_DIR/macos/WaiSay/WaiSay/Assets.xcassets/AppIcon.appiconset/app_icon_256x256@2x.png"
generate_png 512 "$ROOT_DIR/macos/WaiSay/WaiSay/Assets.xcassets/AppIcon.appiconset/app_icon_512x512.png"
generate_png 1024 "$ROOT_DIR/macos/WaiSay/WaiSay/Assets.xcassets/AppIcon.appiconset/app_icon_512x512@2x.png"

echo "Generating Android launcher icons"
generate_png 48 "$ROOT_DIR/android/app/src/main/res/mipmap-mdpi/ic_launcher.png"
generate_png 48 "$ROOT_DIR/android/app/src/main/res/mipmap-mdpi/ic_launcher_round.png"
generate_png 72 "$ROOT_DIR/android/app/src/main/res/mipmap-hdpi/ic_launcher.png"
generate_png 72 "$ROOT_DIR/android/app/src/main/res/mipmap-hdpi/ic_launcher_round.png"
generate_png 96 "$ROOT_DIR/android/app/src/main/res/mipmap-xhdpi/ic_launcher.png"
generate_png 96 "$ROOT_DIR/android/app/src/main/res/mipmap-xhdpi/ic_launcher_round.png"
generate_png 144 "$ROOT_DIR/android/app/src/main/res/mipmap-xxhdpi/ic_launcher.png"
generate_png 144 "$ROOT_DIR/android/app/src/main/res/mipmap-xxhdpi/ic_launcher_round.png"
generate_png 192 "$ROOT_DIR/android/app/src/main/res/mipmap-xxxhdpi/ic_launcher.png"
generate_png 192 "$ROOT_DIR/android/app/src/main/res/mipmap-xxxhdpi/ic_launcher_round.png"

echo "App icons generated."
