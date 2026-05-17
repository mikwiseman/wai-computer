#!/usr/bin/env python3
"""Write Finder view metadata for the macOS installer DMG."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    from ds_store import DSStore
    from mac_alias import Alias
except ImportError as exc:
    raise SystemExit(
        "Required Python modules are missing: ds_store and mac_alias. "
        "Install the current verified packages with: "
        "python3.14 -m pip install ds-store==1.3.2 mac-alias==2.2.3"
    ) from exc


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create .DS_Store metadata for the WaiComputer DMG window."
    )
    parser.add_argument("mount_point", type=Path)
    parser.add_argument("--app-name", default="WaiComputer")
    parser.add_argument("--background", default=".background/background.png")
    parser.add_argument("--window-x", type=int, default=120)
    parser.add_argument("--window-y", type=int, default=120)
    parser.add_argument("--window-width", type=int, default=960)
    parser.add_argument("--window-height", type=int, default=620)
    parser.add_argument("--app-x", type=int, default=330)
    parser.add_argument("--app-y", type=int, default=360)
    parser.add_argument("--applications-x", type=int, default=630)
    parser.add_argument("--applications-y", type=int, default=360)
    return parser.parse_args()


def require_path(path: Path, description: str) -> None:
    if not path.exists():
        raise SystemExit(f"{description} not found: {path}")


def main() -> int:
    args = parse_args()
    mount_point = args.mount_point.resolve()
    app_item = f"{args.app_name}.app"
    background_path = (mount_point / args.background).resolve()

    require_path(mount_point, "DMG mount point")
    require_path(mount_point / app_item, "DMG app bundle")
    require_path(mount_point / "Applications", "DMG Applications symlink")
    require_path(background_path, "DMG Finder background")

    bounds = (
        f"{{{{{args.window_x}, {args.window_y}}}, "
        f"{{{args.window_width}, {args.window_height}}}}}"
    )
    bwsp = {
        "ShowStatusBar": False,
        "WindowBounds": bounds,
        "ContainerShowSidebar": False,
        "PreviewPaneVisibility": False,
        "SidebarWidth": 180,
        "ShowTabView": False,
        "ShowToolbar": False,
        "ShowPathbar": False,
        "ShowSidebar": False,
    }
    icvp = {
        "viewOptionsVersion": 1,
        "backgroundType": 2,
        "backgroundColorRed": 1.0,
        "backgroundColorGreen": 1.0,
        "backgroundColorBlue": 1.0,
        "backgroundImageAlias": Alias.for_file(str(background_path)).to_bytes(),
        "gridOffsetX": 0.0,
        "gridOffsetY": 0.0,
        "gridSpacing": 100.0,
        "arrangeBy": "none",
        "showIconPreview": True,
        "showItemInfo": False,
        "labelOnBottom": True,
        "textSize": 14.0,
        "iconSize": 112.0,
        "scrollPositionX": 0.0,
        "scrollPositionY": 0.0,
    }

    ds_store_path = mount_point / ".DS_Store"
    with DSStore.open(str(ds_store_path), "w+") as store:
        store["."]["vSrn"] = ("long", 1)
        store["."]["bwsp"] = bwsp
        store["."]["icvp"] = icvp
        store["."]["icvl"] = (b"type", b"icnv")
        store[app_item]["Iloc"] = (args.app_x, args.app_y)
        store["Applications"]["Iloc"] = (args.applications_x, args.applications_y)

    return 0


if __name__ == "__main__":
    sys.exit(main())
