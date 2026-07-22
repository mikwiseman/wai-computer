#!/usr/bin/env python3
"""Merge a single-item Sparkle appcast into an existing remote appcast.

Reads the local appcast (containing the new release as its sole <item>),
fetches the existing remote appcast, deduplicates by sparkle:version+channel,
and writes a merged appcast back to the local path.

Sparkle native channels: items without <sparkle:channel> are stable; items
with <sparkle:channel>beta</sparkle:channel> only reach clients that opted
into the beta channel via SPUUpdater.allowedChannels.

Cap: keeps the latest 10 items per channel to keep the feed bounded.

Exit codes:
  0  merged successfully (or remote was empty/missing)
  2  fatal — local appcast malformed or unreadable
  3  fatal — remote fetch failed for a reason other than 404
  4  fatal — an existing enclosure URL has different signature metadata
"""
from __future__ import annotations

import argparse
import sys
import urllib.error
import urllib.request
from xml.etree import ElementTree as ET

SPARKLE_NS = "http://www.andymatuschak.org/xml-namespaces/sparkle"
ET.register_namespace("sparkle", SPARKLE_NS)

ITEMS_PER_CHANNEL = 10
ENCLOSURE_CONFLICT_ATTRS = (
    "length",
    f"{{{SPARKLE_NS}}}edSignature",
    f"{{{SPARKLE_NS}}}dsaSignature",
)


def fetch_remote(url: str, timeout: float = 15.0) -> str | None:
    """Return remote appcast XML, or None if remote is missing (404).

    Raises SystemExit(3) on any other error so we never silently overwrite
    a healthy remote with a single-item local file.
    """
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            print(f"merge-appcast: remote 404 at {url}; treating as first publish", file=sys.stderr)
            return None
        print(f"merge-appcast: HTTP {exc.code} fetching remote appcast: {exc}", file=sys.stderr)
        sys.exit(3)
    except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
        print(f"merge-appcast: network error fetching remote appcast: {exc}", file=sys.stderr)
        sys.exit(3)


def parse_xml(xml_text: str, source_label: str) -> ET.Element:
    try:
        return ET.fromstring(xml_text)
    except ET.ParseError as exc:
        print(f"merge-appcast: malformed XML in {source_label}: {exc}", file=sys.stderr)
        sys.exit(2)


def item_channel(item: ET.Element) -> str:
    el = item.find(f"{{{SPARKLE_NS}}}channel")
    if el is None or not (el.text or "").strip():
        return "stable"
    return el.text.strip()


def item_build(item: ET.Element) -> int:
    el = item.find(f"{{{SPARKLE_NS}}}version")
    if el is None or not (el.text or "").strip():
        return -1
    try:
        return int(el.text.strip())
    except ValueError:
        return -1


def enclosure_signature_key(item: ET.Element) -> tuple[str, str, str] | None:
    enclosure = item.find("enclosure")
    if enclosure is None:
        return None
    url = (enclosure.get("url") or "").strip()
    if not url:
        return None
    return tuple(enclosure.get(attr) or "" for attr in ENCLOSURE_CONFLICT_ATTRS)


def enclosure_url(item: ET.Element) -> str | None:
    enclosure = item.find("enclosure")
    if enclosure is None:
        return None
    url = (enclosure.get("url") or "").strip()
    return url or None


def validate_new_enclosure_url(new_item: ET.Element, existing_items: list[ET.Element]) -> None:
    new_url = enclosure_url(new_item)
    if new_url is None:
        return
    new_signature_key = enclosure_signature_key(new_item)
    if new_signature_key is None:
        return

    for item in existing_items:
        if enclosure_url(item) != new_url:
            continue
        signature_key = enclosure_signature_key(item)
        if signature_key is None or signature_key == new_signature_key:
            continue
        print(
            "merge-appcast: enclosure URL conflict: "
            f"{new_url} is referenced with different signature metadata",
            file=sys.stderr,
        )
        sys.exit(4)


def merge(local_xml: str, remote_xml: str | None) -> str:
    local_root = parse_xml(local_xml, "local appcast")
    local_channel = local_root.find("channel")
    if local_channel is None:
        print("merge-appcast: local appcast missing <channel>", file=sys.stderr)
        sys.exit(2)
    new_items = local_channel.findall("item")
    if len(new_items) != 1:
        print(
            f"merge-appcast: expected exactly 1 <item> in local appcast, got {len(new_items)}",
            file=sys.stderr,
        )
        sys.exit(2)
    new_item = new_items[0]
    new_build = item_build(new_item)
    new_channel = item_channel(new_item)

    if remote_xml is None:
        return ET.tostring(local_root, encoding="unicode", xml_declaration=True)

    remote_root = parse_xml(remote_xml, "remote appcast")
    remote_channel = remote_root.find("channel")
    if remote_channel is None:
        print("merge-appcast: remote appcast missing <channel>; using local-only", file=sys.stderr)
        return ET.tostring(local_root, encoding="unicode", xml_declaration=True)

    remote_items = remote_channel.findall("item")
    validate_new_enclosure_url(new_item, remote_items)

    existing = [
        item for item in remote_items
        if not (item_build(item) == new_build and item_channel(item) == new_channel)
    ]

    by_channel: dict[str, list[ET.Element]] = {}
    by_channel.setdefault(new_channel, []).append(new_item)
    for item in existing:
        by_channel.setdefault(item_channel(item), []).append(item)

    merged_items: list[ET.Element] = []
    for channel, items in by_channel.items():
        items.sort(key=item_build, reverse=True)
        merged_items.extend(items[:ITEMS_PER_CHANNEL])
    merged_items.sort(key=item_build, reverse=True)

    for child in list(remote_channel):
        if child.tag == "item":
            remote_channel.remove(child)
    for item in merged_items:
        remote_channel.append(item)

    return ET.tostring(remote_root, encoding="unicode", xml_declaration=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--local",
        required=True,
        help="Path to local appcast.xml (single new item)",
    )
    parser.add_argument("--remote-url", required=True, help="URL of the live remote appcast.xml")
    parser.add_argument("--out", required=True, help="Path to write merged appcast.xml")
    args = parser.parse_args()

    with open(args.local, "r", encoding="utf-8") as fh:
        local_xml = fh.read()

    remote_xml = fetch_remote(args.remote_url)
    merged = merge(local_xml, remote_xml)

    if not merged.startswith("<?xml"):
        merged = '<?xml version="1.0" encoding="UTF-8"?>\n' + merged

    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(merged)
        if not merged.endswith("\n"):
            fh.write("\n")

    print(f"merge-appcast: wrote merged appcast to {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
