#!/usr/bin/env python3
"""Generate WaiComputer macOS app icon.

Black rounded triangle pointing up with a white retro computer icon inside.
"""

import math
from PIL import Image, ImageDraw


def draw_rounded_triangle(draw, cx, cy, size, corner_radius, fill):
    """Draw an equilateral triangle pointing up with rounded corners."""
    # Equilateral triangle vertices (pointing up)
    h = size * math.sqrt(3) / 2
    # Shift center down slightly so it looks visually centered
    offset_y = size * 0.05
    top = (cx, cy - h * 2 / 3 + offset_y)
    bottom_left = (cx - size / 2, cy + h / 3 + offset_y)
    bottom_right = (cx + size / 2, cy + h / 3 + offset_y)

    vertices = [top, bottom_right, bottom_left]

    # For rounded corners, we draw circles at corners and a polygon body
    # Use a simpler approach: draw the triangle as a polygon and overlay circles
    # at each vertex for rounding effect

    # Actually, let's use a proper rounded polygon approach
    # For each corner, we offset inward along both edges and draw an arc

    rounded_points = []
    n = len(vertices)

    for i in range(n):
        p_prev = vertices[(i - 1) % n]
        p_curr = vertices[i]
        p_next = vertices[(i + 1) % n]

        # Vectors from current to prev and next
        dx1 = p_prev[0] - p_curr[0]
        dy1 = p_prev[1] - p_curr[1]
        dx2 = p_next[0] - p_curr[0]
        dy2 = p_next[1] - p_curr[1]

        len1 = math.sqrt(dx1 * dx1 + dy1 * dy1)
        len2 = math.sqrt(dx2 * dx2 + dy2 * dy2)

        # Normalize
        dx1 /= len1
        dy1 /= len1
        dx2 /= len2
        dy2 /= len2

        # Offset points along edges
        r = corner_radius
        p1 = (p_curr[0] + dx1 * r, p_curr[1] + dy1 * r)
        p2 = (p_curr[0] + dx2 * r, p_curr[1] + dy2 * r)

        # Generate arc points between p1 and p2 around corner
        # Find center of arc
        # Bisector direction
        bx = dx1 + dx2
        by = dy1 + dy2
        blen = math.sqrt(bx * bx + by * by)
        if blen > 0:
            bx /= blen
            by /= blen

        # Half angle between edges
        dot = dx1 * dx2 + dy1 * dy2
        dot = max(-1, min(1, dot))
        half_angle = math.acos(dot) / 2

        # Distance from corner to arc center
        d = r / math.sin(half_angle)
        arc_center = (p_curr[0] + bx * d, p_curr[1] + by * d)

        # Start and end angles for the arc
        angle1 = math.atan2(p1[1] - arc_center[1], p1[0] - arc_center[0])
        angle2 = math.atan2(p2[1] - arc_center[1], p2[0] - arc_center[0])

        # Generate arc points (going from angle1 to angle2)
        # Determine direction
        cross = dx1 * dy2 - dy1 * dx2
        if cross > 0:
            # Go counterclockwise
            if angle2 > angle1:
                angle2 -= 2 * math.pi
            steps = 20
            for s in range(steps + 1):
                t = s / steps
                a = angle1 + t * (angle2 - angle1)
                px = arc_center[0] + r * math.cos(a)
                py = arc_center[1] + r * math.sin(a)
                rounded_points.append((px, py))
        else:
            # Go clockwise
            if angle2 < angle1:
                angle2 += 2 * math.pi
            steps = 20
            for s in range(steps + 1):
                t = s / steps
                a = angle1 + t * (angle2 - angle1)
                px = arc_center[0] + r * math.cos(a)
                py = arc_center[1] + r * math.sin(a)
                rounded_points.append((px, py))

    draw.polygon(rounded_points, fill=fill)


def draw_retro_computer(draw, cx, cy, size, fill):
    """Draw a simple retro computer icon (monitor + stand)."""
    # Monitor body (wider than tall)
    monitor_w = size * 0.60
    monitor_h = size * 0.42
    monitor_top = cy - size * 0.28
    monitor_left = cx - monitor_w / 2
    monitor_right = cx + monitor_w / 2
    monitor_bottom = monitor_top + monitor_h

    # Monitor outer frame with rounded corners
    frame_radius = size * 0.04
    draw.rounded_rectangle(
        [monitor_left, monitor_top, monitor_right, monitor_bottom],
        radius=frame_radius,
        fill=fill,
    )

    # Screen bezel (inner dark area to simulate screen)
    bezel = size * 0.045
    screen_left = monitor_left + bezel
    screen_top = monitor_top + bezel
    screen_right = monitor_right - bezel
    screen_bottom = monitor_bottom - bezel * 1.8  # More bezel at bottom (chin)
    screen_radius = size * 0.02

    # Draw screen as a dark rectangle inside the white monitor
    draw.rounded_rectangle(
        [screen_left, screen_top, screen_right, screen_bottom],
        radius=screen_radius,
        fill=(0, 0, 0),  # Black screen
    )

    # Neck/stand column
    neck_w = size * 0.10
    neck_h = size * 0.10
    neck_left = cx - neck_w / 2
    neck_top = monitor_bottom
    neck_bottom = neck_top + neck_h

    draw.rectangle(
        [neck_left, neck_top, neck_left + neck_w, neck_bottom],
        fill=fill,
    )

    # Base (wider, flat)
    base_w = size * 0.35
    base_h = size * 0.045
    base_left = cx - base_w / 2
    base_top = neck_bottom
    base_bottom = base_top + base_h
    base_radius = size * 0.02

    draw.rounded_rectangle(
        [base_left, base_top, base_left + base_w, base_bottom],
        radius=base_radius,
        fill=fill,
    )


def generate_icon(size):
    """Generate icon at specified size."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    cx, cy = size / 2, size / 2
    padding = size * 0.10
    triangle_size = size - padding * 2
    corner_radius = triangle_size * 0.06

    # Draw black rounded triangle
    draw_rounded_triangle(draw, cx, cy, triangle_size, corner_radius, fill=(0, 0, 0))

    # Draw white retro computer inside the triangle
    computer_size = triangle_size * 0.50
    # Shift computer down slightly since triangle top is pointy
    computer_cy = cy + triangle_size * 0.06
    draw_retro_computer(draw, cx, computer_cy, computer_size, fill=(255, 255, 255))

    return img


def main():
    output_dir = "/Users/mikwiseman/Documents/Code/wai-computer/macos/WaiComputer/WaiComputer/Assets.xcassets/AppIcon.appiconset"

    # macOS icon sizes: (points, scale, pixel_size)
    sizes = [
        (16, 1, 16),
        (16, 2, 32),
        (32, 1, 32),
        (32, 2, 64),
        (128, 1, 128),
        (128, 2, 256),
        (256, 1, 256),
        (256, 2, 512),
        (512, 1, 512),
        (512, 2, 1024),
    ]

    # Generate master at 1024 and resize down for quality
    master = generate_icon(1024)

    for points, scale, pixels in sizes:
        if pixels == 1024:
            icon = master.copy()
        else:
            icon = master.resize((pixels, pixels), Image.LANCZOS)

        suffix = f"_{points}x{points}" if scale == 1 else f"_{points}x{points}@2x"
        filename = f"app_icon{suffix}.png"
        filepath = f"{output_dir}/{filename}"
        icon.save(filepath, "PNG")
        print(f"Generated {filename} ({pixels}x{pixels})")

    # Generate Contents.json
    import json

    contents = {
        "images": [],
        "info": {"author": "xcode", "version": 1},
    }

    for points, scale, pixels in sizes:
        suffix = f"_{points}x{points}" if scale == 1 else f"_{points}x{points}@2x"
        filename = f"app_icon{suffix}.png"
        contents["images"].append(
            {
                "filename": filename,
                "idiom": "mac",
                "scale": f"{scale}x",
                "size": f"{points}x{points}",
            }
        )

    contents_path = f"{output_dir}/Contents.json"
    with open(contents_path, "w") as f:
        json.dump(contents, f, indent=2)
    print(f"Generated Contents.json")


if __name__ == "__main__":
    main()
