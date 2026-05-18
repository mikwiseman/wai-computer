#!/usr/bin/env python3
"""Generate deterministic WaiComputer app icon source assets."""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter


ROOT_DIR = Path(__file__).resolve().parents[1]
SOURCE_LIGHT = ROOT_DIR / "assets/app-icon-1024.png"
SOURCE_DARK = ROOT_DIR / "assets/app-icon-1024-dark.png"
LAYER_LIGHT = ROOT_DIR / "assets/app-icon-1024-layer.png"
LAYER_DARK = ROOT_DIR / "assets/app-icon-1024-layer-dark.png"

BG_TOP = (31, 33, 38)
BG_BOTTOM = (8, 10, 13)
TRIANGLE_LIGHT = (246, 245, 240)
TRIANGLE_DARK = (16, 18, 22)


def lerp(a: int, b: int, t: float) -> int:
    return round(a + (b - a) * t)


def vertical_gradient(size: int, top: tuple[int, int, int], bottom: tuple[int, int, int]) -> Image.Image:
    image = Image.new("RGB", (size, size), top)
    draw = ImageDraw.Draw(image)
    for y in range(size):
        t = y / (size - 1)
        color = tuple(lerp(top[index], bottom[index], t) for index in range(3))
        draw.line([(0, y), (size, y)], fill=color)
    return image


def rounded_triangle_points(cx: float, cy: float, size: float, radius: float) -> list[tuple[float, float]]:
    height = size * math.sqrt(3) / 2
    offset_y = size * 0.035
    vertices = [
        (cx, cy - height * 2 / 3 + offset_y),
        (cx + size / 2, cy + height / 3 + offset_y),
        (cx - size / 2, cy + height / 3 + offset_y),
    ]

    points: list[tuple[float, float]] = []
    for index, current in enumerate(vertices):
        previous = vertices[(index - 1) % len(vertices)]
        next_point = vertices[(index + 1) % len(vertices)]

        v1x = previous[0] - current[0]
        v1y = previous[1] - current[1]
        v2x = next_point[0] - current[0]
        v2y = next_point[1] - current[1]
        len1 = math.hypot(v1x, v1y)
        len2 = math.hypot(v2x, v2y)
        v1x, v1y = v1x / len1, v1y / len1
        v2x, v2y = v2x / len2, v2y / len2

        start = (current[0] + v1x * radius, current[1] + v1y * radius)
        end = (current[0] + v2x * radius, current[1] + v2y * radius)

        bisector_x = v1x + v2x
        bisector_y = v1y + v2y
        bisector_length = math.hypot(bisector_x, bisector_y)
        if bisector_length == 0:
            points.append(current)
            continue
        bisector_x /= bisector_length
        bisector_y /= bisector_length

        dot = max(-1.0, min(1.0, v1x * v2x + v1y * v2y))
        half_angle = math.acos(dot) / 2
        center_distance = radius / math.sin(half_angle)
        arc_center = (
            current[0] + bisector_x * center_distance,
            current[1] + bisector_y * center_distance,
        )

        angle1 = math.atan2(start[1] - arc_center[1], start[0] - arc_center[0])
        angle2 = math.atan2(end[1] - arc_center[1], end[0] - arc_center[0])
        cross = v1x * v2y - v1y * v2x
        if cross > 0 and angle2 > angle1:
            angle2 -= math.tau
        elif cross <= 0 and angle2 < angle1:
            angle2 += math.tau

        for step in range(18):
            t = step / 17
            angle = angle1 + (angle2 - angle1) * t
            points.append(
                (
                    arc_center[0] + radius * math.cos(angle),
                    arc_center[1] + radius * math.sin(angle),
                )
            )
    return points


def draw_foreground(size: int, dark: bool) -> Image.Image:
    scale = size / 1024
    layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    cx, cy = size / 2, size / 2 + 8 * scale

    triangle_size = size * 0.68
    triangle_points = rounded_triangle_points(cx, cy, triangle_size, triangle_size * 0.055)
    triangle_mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(triangle_mask).polygon(triangle_points, fill=255)

    shadow_mask = triangle_mask.filter(ImageFilter.GaussianBlur(16 * scale))
    layer.alpha_composite(
        Image.composite(
            Image.new("RGBA", (size, size), (0, 0, 0, 88 if dark else 76)),
            Image.new("RGBA", (size, size), (0, 0, 0, 0)),
            shadow_mask,
        ),
        (0, round(14 * scale)),
    )

    triangle_fill = TRIANGLE_LIGHT if not dark else (255, 255, 250)
    layer.alpha_composite(
        Image.composite(
            Image.new("RGBA", (size, size), (*triangle_fill, 255)),
            Image.new("RGBA", (size, size), (0, 0, 0, 0)),
            triangle_mask,
        )
    )

    draw = ImageDraw.Draw(layer)
    bar_fill = TRIANGLE_DARK
    bar_shadow = (255, 255, 255, 24)
    heights = [54, 84, 116, 156, 205, 262, 336, 278, 214, 154, 104, 68]
    bar_width = 26 * scale
    gap = 14 * scale
    total_width = len(heights) * bar_width + (len(heights) - 1) * gap
    baseline = cy + triangle_size * 0.24
    start_x = cx - total_width / 2

    for index, height in enumerate(heights):
        x0 = start_x + index * (bar_width + gap)
        x1 = x0 + bar_width
        y1 = baseline
        y0 = baseline - height * scale
        radius = bar_width * 0.48
        draw.rounded_rectangle(
            [x0 + 3 * scale, y0 + 5 * scale, x1 + 3 * scale, y1 + 5 * scale],
            radius=radius,
            fill=bar_shadow,
        )
        draw.rounded_rectangle([x0, y0, x1, y1], radius=radius, fill=(*bar_fill, 246))

    return layer


def draw_full_icon(size: int, dark: bool) -> Image.Image:
    background = vertical_gradient(
        size,
        (24, 26, 31) if not dark else (12, 14, 18),
        (7, 8, 11) if not dark else (2, 3, 5),
    ).convert("RGBA")

    draw = ImageDraw.Draw(background, "RGBA")
    for inset, alpha in ((0.04, 22), (0.08, 12)):
        draw.rounded_rectangle(
            [size * inset, size * inset, size * (1 - inset), size * (1 - inset)],
            radius=size * 0.18,
            outline=(255, 255, 255, alpha),
            width=max(1, round(size * 0.006)),
        )
    background.alpha_composite(draw_foreground(size, dark))
    return background.convert("RGB")


def save_icon(path: Path, image: Image.Image) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, "PNG", optimize=True)
    print(f"Generated {path.relative_to(ROOT_DIR)}")


def main() -> None:
    save_icon(SOURCE_LIGHT, draw_full_icon(1024, dark=False))
    save_icon(SOURCE_DARK, draw_full_icon(1024, dark=True))
    save_icon(LAYER_LIGHT, draw_foreground(1024, dark=False))
    save_icon(LAYER_DARK, draw_foreground(1024, dark=True))


if __name__ == "__main__":
    main()
