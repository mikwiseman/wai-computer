#!/usr/bin/env python3
"""Generate WaiComputer icon vector assets from one geometry source.

The mark is a triangle (mountain) with an audio waveform knocked out of it,
authored as a single compound path with ``fill-rule="evenodd"`` so it can be
recoloured per Apple appearance. Geometry is traced from the reference artwork
in 1254x1254 space and re-projected into each target's canvas / safe zone:

  * assets/icon/foreground.svg                    - Apple AppIcon.icon glyph (1024)
  * assets/icon/mark-tight.svg                    - tight square mark (macOS menu bar)

Per Apple's Icon Composer guidance nothing is baked in (no background, shadow,
or canvas mask). Rasters (app icons, favicon, BrandIcon, launcher mipmaps) are
produced from these + the raster master by scripts/generate-app-icons.sh.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# --- geometry, traced from the reference artwork (1254 x 1254 space) ---
TRIANGLE = [(627.9, 178.0), (1126.0, 1013.0), (126.0, 1013.0)]  # apex, base-R, base-L
BAR_BASELINE = 974.0
BAR_WIDTH = 57.0
BARS = [  # (center_x, top_y) sharing the baseline; two-hump rhythm, peak at bar 7
    (267.5, 860.0), (353.0, 764.0), (437.0, 702.0), (522.0, 751.0),
    (607.0, 807.0), (695.5, 670.0), (779.5, 603.0), (865.0, 659.0), (951.0, 844.0),
]


def _f(v: float) -> str:
    return f"{v:.3f}".rstrip("0").rstrip(".")


def compound_path(scale: float, ox: float, oy: float) -> str:
    """Triangle + waveform knockout path, mapping reference coords via p*scale+offset."""
    def X(x: float) -> str: return _f(x * scale + ox)
    def Y(y: float) -> str: return _f(y * scale + oy)

    (apx, apy), (brx, bry), (blx, bly) = TRIANGLE
    parts = [f"M{X(apx)},{Y(apy)} L{X(brx)},{Y(bry)} L{X(blx)},{Y(bly)} Z"]

    half = BAR_WIDTH / 2.0
    rr = half * scale
    for bcx, top in BARS:
        x0 = (bcx - half) * scale + ox
        x1 = (bcx + half) * scale + ox
        y0 = top * scale + oy
        y1 = BAR_BASELINE * scale + oy
        parts.append(
            f"M{_f(x0 + rr)},{_f(y0)} L{_f(x1 - rr)},{_f(y0)} "
            f"A{_f(rr)},{_f(rr)} 0 0 1 {_f(x1)},{_f(y0 + rr)} "
            f"L{_f(x1)},{_f(y1 - rr)} "
            f"A{_f(rr)},{_f(rr)} 0 0 1 {_f(x1 - rr)},{_f(y1)} "
            f"L{_f(x0 + rr)},{_f(y1)} "
            f"A{_f(rr)},{_f(rr)} 0 0 1 {_f(x0)},{_f(y1 - rr)} "
            f"L{_f(x0)},{_f(y0 + rr)} "
            f"A{_f(rr)},{_f(rr)} 0 0 1 {_f(x0 + rr)},{_f(y0)} Z"
        )
    return " ".join(parts)


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    print(f"Wrote {path.relative_to(ROOT)}")


def svg(d: str, size: int) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{size}" height="{size}" viewBox="0 0 {size} {size}">\n'
        f'  <path fill="#111318" fill-rule="evenodd" d="{d}"/>\n'
        f"</svg>\n"
    )


def main() -> None:
    cx_ref = (TRIANGLE[2][0] + TRIANGLE[1][0]) / 2.0   # triangle horizontal centre
    cy_ref = (TRIANGLE[0][1] + TRIANGLE[1][1]) / 2.0   # triangle vertical centre

    # 1) Apple AppIcon.icon glyph: 1024 canvas, reference margins preserved.
    s = 1024 / 1254.0
    write(ROOT / "assets/icon/foreground.svg", svg(compound_path(s, 0.0, 0.0), 1024))

    # 2) Tight square mark for the macOS menu-bar template (mark fills ~88% width).
    V, st = 100, 0.088
    ox = V / 2 - cx_ref * st
    oy = V / 2 - cy_ref * st
    write(ROOT / "assets/icon/mark-tight.svg", svg(compound_path(st, ox, oy), V))


if __name__ == "__main__":
    main()
