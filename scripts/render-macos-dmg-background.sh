#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "$0")/.." && pwd)
OUTPUT_PATH=${1:?"usage: render-macos-dmg-background.sh <output-path> [icon-path] [base-background]"}
ICON_PATH=${2:-"$ROOT_DIR/macos/WaiComputer/WaiComputer/Assets.xcassets/AppIcon.appiconset/app_icon_512x512@2x.png"}
BASE_BACKGROUND_PATH=${3:-}

mkdir -p "$(dirname "$OUTPUT_PATH")"

python3 - "$OUTPUT_PATH" "$ICON_PATH" "$BASE_BACKGROUND_PATH" <<'PY'
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps
from pathlib import Path
import sys

output_path = Path(sys.argv[1])
icon_path = Path(sys.argv[2])
base_background_path = Path(sys.argv[3]) if len(sys.argv) > 3 and sys.argv[3] else None
if not icon_path.exists():
    raise SystemExit(f"Icon file not found: {icon_path}")

W, H = 960, 620


def fit_cover(image):
    image = image.convert("RGBA")
    src_w, src_h = image.size
    scale = max(W / src_w, H / src_h)
    resized = image.resize((int(round(src_w * scale)), int(round(src_h * scale))), Image.Resampling.LANCZOS)
    left = max(0, (resized.width - W) // 2)
    top = max(0, (resized.height - H) // 2)
    return resized.crop((left, top, left + W, top + H))

if base_background_path and base_background_path.exists():
    base = fit_cover(Image.open(base_background_path))
    base = ImageOps.grayscale(base).convert("RGBA")
    paper = Image.new("RGBA", (W, H), (246, 244, 238, 255))
    canvas = Image.blend(paper, base, 0.16)
else:
    canvas = Image.new("RGBA", (W, H))
    pix = canvas.load()
    for y in range(H):
        t = y / (H - 1)
        top = (248, 246, 241)
        bottom = (242, 240, 235)
        row = tuple(int(top[i] * (1 - t) + bottom[i] * t) for i in range(3)) + (255,)
        for x in range(W):
            pix[x, y] = row
    linework = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    line_draw = ImageDraw.Draw(linework)
    line_draw.arc((-120, 112, 420, 660), start=202, end=325, fill=(32, 32, 32, 18), width=2)
    line_draw.arc((544, -40, 1090, 570), start=220, end=342, fill=(32, 32, 32, 16), width=2)
    linework = linework.filter(ImageFilter.GaussianBlur(0.4))
    canvas = Image.alpha_composite(canvas, linework)

guide = Image.new("RGBA", (W, H), (0, 0, 0, 0))
guide_draw = ImageDraw.Draw(guide)
guide_draw.line((406, 352, 552, 352), fill=(24, 24, 24, 160), width=3)
guide_draw.polygon(((552, 352), (536, 342), (536, 362)), fill=(24, 24, 24, 160))
canvas = Image.alpha_composite(canvas, guide)


def load_font(path, size):
    return ImageFont.truetype(str(path), size=size)


def centered_text(draw, text, font, y, fill):
    bbox = draw.textbbox((0, 0), text, font=font)
    x = (W - (bbox[2] - bbox[0])) / 2
    draw.text((x, y), text, font=font, fill=fill)


title_font = load_font(Path("/System/Library/Fonts/Avenir Next.ttc"), 26)
text = Image.new("RGBA", (W, H), (0, 0, 0, 0))
draw = ImageDraw.Draw(text)
centered_text(draw, "Drag to Applications", title_font, 92, (22, 22, 22, 196))
canvas = Image.alpha_composite(canvas, text)

output_path.parent.mkdir(parents=True, exist_ok=True)
canvas.save(output_path)
PY
