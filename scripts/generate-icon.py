#!/usr/bin/env python3
"""Generate WaiComputer app icon source assets from the canonical artwork."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageOps


ROOT_DIR = Path(__file__).resolve().parents[1]
SOURCE_ARTWORK = ROOT_DIR / "assets/app-icon-source.png"
SOURCE_LIGHT = ROOT_DIR / "assets/app-icon-1024.png"
SOURCE_DARK = ROOT_DIR / "assets/app-icon-1024-dark.png"
LAYER_LIGHT = ROOT_DIR / "assets/app-icon-1024-layer.png"
LAYER_DARK = ROOT_DIR / "assets/app-icon-1024-layer-dark.png"


def normalize_square(source: Image.Image, size: int) -> Image.Image:
    image = source.convert("RGB")
    width, height = image.size
    side = min(width, height)
    left = (width - side) // 2
    top = (height - side) // 2
    cropped = image.crop((left, top, left + side, top + side))
    return cropped.resize((size, size), Image.Resampling.LANCZOS)


def dark_variant(light_icon: Image.Image) -> Image.Image:
    return ImageOps.invert(light_icon.convert("RGB"))


def save_icon(path: Path, image: Image.Image) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, "PNG", optimize=True)
    print(f"Generated {path.relative_to(ROOT_DIR)}")


def main() -> None:
    if not SOURCE_ARTWORK.exists():
        raise SystemExit(f"Source artwork not found: {SOURCE_ARTWORK}")

    light_icon = normalize_square(Image.open(SOURCE_ARTWORK), 1024)
    dark_icon = dark_variant(light_icon)

    save_icon(SOURCE_LIGHT, light_icon)
    save_icon(SOURCE_DARK, dark_icon)
    save_icon(LAYER_LIGHT, light_icon)
    save_icon(LAYER_DARK, dark_icon)


if __name__ == "__main__":
    main()
