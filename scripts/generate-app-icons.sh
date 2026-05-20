#!/bin/bash
# Generate WaiComputer app-icon assets.
#
# Source of truth for the Apple icon is assets/icon/foreground.svg, consumed
# directly by AppIcon.icon (Icon Composer) on macOS and iOS. The system renders
# the light / dark / tinted appearances at build time and auto-generates the
# legacy .icns fallback for older OS versions -- so there is NO colour inversion
# and NO hand-maintained .appiconset.
#
# The raster targets (web favicon/marketing icon, Android flat launcher
# mipmaps, onboarding BrandIcon) are resized from the raster master
# assets/app-icon-1024.png. The Apple glyph, the macOS menu-bar template, and
# the Android *adaptive* vector drawables are emitted by generate-icon.py.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
GLYPH_SVG="$ROOT_DIR/assets/icon/foreground.svg"
GLYPH_TIGHT="$ROOT_DIR/assets/icon/mark-tight.svg"
SOURCE_ICON="${1:-$ROOT_DIR/assets/app-icon-1024.png}"

# 1. Refresh the Apple icon glyph; macOS + iOS share one AppIcon.icon layer.
python3 "$ROOT_DIR/scripts/generate-icon.py"
cp "$GLYPH_SVG" "$ROOT_DIR/macos/WaiComputer/WaiComputer/AppIcon.icon/Assets/foreground.svg"
cp "$GLYPH_SVG" "$ROOT_DIR/ios/WaiComputer/WaiComputer/AppIcon.icon/Assets/foreground.svg"
echo "Updated AppIcon.icon layers (macOS + iOS)"

generate_png() {
  local size="$1" destination="$2"
  mkdir -p "$(dirname "$destination")"
  sips -z "$size" "$size" "$SOURCE_ICON" --out "$destination" >/dev/null
}

# 2. Onboarding BrandIcon (iOS + macOS).
generate_png 256 "$ROOT_DIR/ios/WaiComputer/WaiComputer/Assets.xcassets/BrandIcon.imageset/brand-icon.png"
generate_png 512 "$ROOT_DIR/ios/WaiComputer/WaiComputer/Assets.xcassets/BrandIcon.imageset/brand-icon@2x.png"
generate_png 256 "$ROOT_DIR/macos/WaiComputer/WaiComputer/Assets.xcassets/BrandIcon.imageset/brand-icon.png"
generate_png 512 "$ROOT_DIR/macos/WaiComputer/WaiComputer/Assets.xcassets/BrandIcon.imageset/brand-icon@2x.png"

# 2b. macOS menu-bar icon: tight transparent glyph (the imageset renders it as a template).
MENUBAR="$ROOT_DIR/macos/WaiComputer/WaiComputer/Assets.xcassets/BrandIconMenuBar.imageset"
rsvg-convert -w 22 -h 22 "$GLYPH_TIGHT" -o "$MENUBAR/brand-icon-menubar.png"
rsvg-convert -w 44 -h 44 "$GLYPH_TIGHT" -o "$MENUBAR/brand-icon-menubar@2x.png"

# 3. Web marketing icon + favicon.
generate_png 1024 "$ROOT_DIR/web/public/app-icon.png"
python3 - "$SOURCE_ICON" "$ROOT_DIR/web/src/app/favicon.ico" <<'PY'
import sys
from PIL import Image

source = Image.open(sys.argv[1]).convert("RGBA")
source.save(sys.argv[2], format="ICO", sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
PY

# 4. Android flat launcher mipmaps (adaptive vector drawables stay as-is).
generate_png 48  "$ROOT_DIR/android/app/src/main/res/mipmap-mdpi/ic_launcher.png"
generate_png 48  "$ROOT_DIR/android/app/src/main/res/mipmap-mdpi/ic_launcher_round.png"
generate_png 72  "$ROOT_DIR/android/app/src/main/res/mipmap-hdpi/ic_launcher.png"
generate_png 72  "$ROOT_DIR/android/app/src/main/res/mipmap-hdpi/ic_launcher_round.png"
generate_png 96  "$ROOT_DIR/android/app/src/main/res/mipmap-xhdpi/ic_launcher.png"
generate_png 96  "$ROOT_DIR/android/app/src/main/res/mipmap-xhdpi/ic_launcher_round.png"
generate_png 144 "$ROOT_DIR/android/app/src/main/res/mipmap-xxhdpi/ic_launcher.png"
generate_png 144 "$ROOT_DIR/android/app/src/main/res/mipmap-xxhdpi/ic_launcher_round.png"
generate_png 192 "$ROOT_DIR/android/app/src/main/res/mipmap-xxxhdpi/ic_launcher.png"
generate_png 192 "$ROOT_DIR/android/app/src/main/res/mipmap-xxxhdpi/ic_launcher_round.png"

echo "App icons generated."
