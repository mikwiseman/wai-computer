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

DARK_ICON="${SOURCE_ICON%.*}-dark.${SOURCE_ICON##*.}"
if [[ ! -f "$DARK_ICON" ]]; then
  echo "Generating dark variant from $SOURCE_ICON"
  python3 - "$SOURCE_ICON" "$DARK_ICON" <<'PY'
import sys
from PIL import Image
import numpy as np
src = Image.open(sys.argv[1]).convert("RGBA")
arr = np.array(src)
arr[:, :, :3] = 255 - arr[:, :, :3]
Image.fromarray(arr, "RGBA").save(sys.argv[2], "PNG")
PY
fi

generate_dark_png() {
  local size="$1"
  local destination="$2"
  mkdir -p "$(dirname "$destination")"
  sips -z "$size" "$size" "$DARK_ICON" --out "$destination" >/dev/null
}

echo "Generating iOS app icons from $SOURCE_ICON"
generate_png 1024 "$ROOT_DIR/ios/WaiComputer/WaiComputer/Assets.xcassets/AppIcon.appiconset/icon-1024.png"
generate_dark_png 1024 "$ROOT_DIR/ios/WaiComputer/WaiComputer/Assets.xcassets/AppIcon.appiconset/icon-1024-dark.png"
cp "$ROOT_DIR/ios/WaiComputer/WaiComputer/Assets.xcassets/AppIcon.appiconset/icon-1024.png" \
  "$ROOT_DIR/ios/WaiComputer/WaiComputer/Assets.xcassets/AppIcon.appiconset/icon-1024-tinted.png"

echo "Refreshing AppIcon.icon dark layers"
cp "$DARK_ICON" "$ROOT_DIR/macos/WaiComputer/WaiComputer/AppIcon.icon/Assets/72eb7034-4bcb-4a4c-b842-bd0dac562f7e-dark.png"
cp "$DARK_ICON" "$ROOT_DIR/ios/WaiComputer/WaiComputer/AppIcon.icon/Assets/72eb7034-4bcb-4a4c-b842-bd0dac562f7e-dark.png"

echo "Generating macOS app icons"
generate_png 16 "$ROOT_DIR/macos/WaiComputer/WaiComputer/Assets.xcassets/AppIcon.appiconset/app_icon_16x16.png"
generate_png 32 "$ROOT_DIR/macos/WaiComputer/WaiComputer/Assets.xcassets/AppIcon.appiconset/app_icon_16x16@2x.png"
generate_png 32 "$ROOT_DIR/macos/WaiComputer/WaiComputer/Assets.xcassets/AppIcon.appiconset/app_icon_32x32.png"
generate_png 64 "$ROOT_DIR/macos/WaiComputer/WaiComputer/Assets.xcassets/AppIcon.appiconset/app_icon_32x32@2x.png"
generate_png 128 "$ROOT_DIR/macos/WaiComputer/WaiComputer/Assets.xcassets/AppIcon.appiconset/app_icon_128x128.png"
generate_png 256 "$ROOT_DIR/macos/WaiComputer/WaiComputer/Assets.xcassets/AppIcon.appiconset/app_icon_128x128@2x.png"
generate_png 256 "$ROOT_DIR/macos/WaiComputer/WaiComputer/Assets.xcassets/AppIcon.appiconset/app_icon_256x256.png"
generate_png 512 "$ROOT_DIR/macos/WaiComputer/WaiComputer/Assets.xcassets/AppIcon.appiconset/app_icon_256x256@2x.png"
generate_png 512 "$ROOT_DIR/macos/WaiComputer/WaiComputer/Assets.xcassets/AppIcon.appiconset/app_icon_512x512.png"
generate_png 1024 "$ROOT_DIR/macos/WaiComputer/WaiComputer/Assets.xcassets/AppIcon.appiconset/app_icon_512x512@2x.png"

echo "Generating onboarding and web icons"
generate_png 256 "$ROOT_DIR/ios/WaiComputer/WaiComputer/Assets.xcassets/BrandIcon.imageset/brand-icon.png"
generate_png 512 "$ROOT_DIR/ios/WaiComputer/WaiComputer/Assets.xcassets/BrandIcon.imageset/brand-icon@2x.png"
generate_png 256 "$ROOT_DIR/macos/WaiComputer/WaiComputer/Assets.xcassets/BrandIcon.imageset/brand-icon.png"
generate_png 512 "$ROOT_DIR/macos/WaiComputer/WaiComputer/Assets.xcassets/BrandIcon.imageset/brand-icon@2x.png"
generate_png 1024 "$ROOT_DIR/web/public/app-icon.png"

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
