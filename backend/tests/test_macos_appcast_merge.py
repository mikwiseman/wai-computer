"""Regression tests for macOS Sparkle appcast publishing."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest


def _load_merge_script() -> ModuleType:
    path = Path(__file__).resolve().parents[2] / "scripts" / "merge-macos-appcast.py"
    spec = importlib.util.spec_from_file_location("merge_macos_appcast", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _appcast(*items: str) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:sparkle="http://www.andymatuschak.org/xml-namespaces/sparkle">
  <channel>
    <title>WaiComputer</title>
    {''.join(items)}
  </channel>
</rss>
"""


def _item(channel_xml: str, length: str, signature: str, url: str, version: str = "89") -> str:
    return f"""
    <item>
      <title>WaiComputer 1.0.12</title>
      {channel_xml}
      <sparkle:version>{version}</sparkle:version>
      <enclosure
        url="{url}"
        type="application/x-apple-diskimage"
        sparkle:edSignature="{signature}"
        length="{length}"
      />
    </item>
"""


def test_merge_rejects_same_enclosure_url_with_different_signature_metadata():
    merge_script = _load_merge_script()
    url = "https://wai.computer/releases/macos/1.0.12-89/WaiComputer-1.0.12-89.dmg"
    local = _appcast(_item("<sparkle:channel>beta</sparkle:channel>", "200", "beta", url))
    remote = _appcast(_item("", "100", "stable", url))

    with pytest.raises(SystemExit) as exc:
        merge_script.merge(local, remote)

    assert exc.value.code == 4


def test_merge_allows_same_build_channels_when_enclosure_urls_differ():
    merge_script = _load_merge_script()
    local = _appcast(
        _item(
            "<sparkle:channel>beta</sparkle:channel>",
            "200",
            "beta",
            "https://wai.computer/releases/macos/1.0.12-89-beta/WaiComputer-1.0.12-89.dmg",
        )
    )
    remote = _appcast(
        _item(
            "",
            "100",
            "stable",
            "https://wai.computer/releases/macos/1.0.12-89/WaiComputer-1.0.12-89.dmg",
        )
    )

    merged = merge_script.merge(local, remote)

    assert "1.0.12-89-beta/WaiComputer-1.0.12-89.dmg" in merged
    assert "1.0.12-89/WaiComputer-1.0.12-89.dmg" in merged


def test_merge_ignores_preexisting_remote_enclosure_conflicts_for_other_urls():
    merge_script = _load_merge_script()
    old_url = "https://wai.computer/releases/macos/1.0.12-85/WaiComputer-1.0.12-85.dmg"
    local_url = "https://wai.computer/releases/macos/1.0.12-90/WaiComputer-1.0.12-90.dmg"
    local = _appcast(_item("", "300", "stable-90", local_url, version="90"))
    remote = _appcast(
        _item("", "100", "stable-85", old_url, version="85"),
        _item("<sparkle:channel>beta</sparkle:channel>", "200", "beta-85", old_url, version="85"),
    )

    merged = merge_script.merge(local, remote)

    assert local_url in merged
    assert old_url in merged


def test_release_scripts_publish_channel_specific_release_slug():
    root = Path(__file__).resolve().parents[2]
    build_script = (root / "scripts" / "build-macos-dmg.sh").read_text(encoding="utf-8")
    publish_script = (root / "scripts" / "publish-macos-dmg.sh").read_text(encoding="utf-8")

    assert 'RELEASE_SLUG="${VERSION}-${BUILD}-${RELEASE_CHANNEL}"' in build_script
    assert 'DOWNLOAD_URL="${SPARKLE_DOWNLOAD_BASE_URL}/${RELEASE_SLUG}/' in build_script
    assert "release_slug=${RELEASE_SLUG}" in build_script
    assert 'RELEASE_SLUG=$(awk -F= \'$1 == "release_slug" {print $2}\'' in publish_script
    assert 'RELEASE_DIR="$RELEASE_ROOT/${RELEASE_SLUG}"' in publish_script


def test_release_notes_find_previous_build_addition_not_current_removal():
    root = Path(__file__).resolve().parents[2]
    build_script = (root / "scripts" / "build-macos-dmg.sh").read_text(encoding="utf-8")

    assert "find_previous_build_commit()" in build_script
    assert 'prev_commit=$(find_previous_build_commit "$prev_build")' in build_script
    assert 'CURRENT_PROJECT_VERSION: \\"${target_build}\\"' in build_script
    assert 'git log -S "CURRENT_PROJECT_VERSION: \\"${prev_build}\\""' not in build_script


def test_release_staples_and_checks_copied_sparkle_updater_before_host_app():
    root = Path(__file__).resolve().parents[2]
    build_script = (root / "scripts" / "build-macos-dmg.sh").read_text(encoding="utf-8")

    helper_staple = 'xcrun stapler staple "$SPARKLE_UPDATER_APP"'
    helper_validate = 'xcrun stapler validate "$SPARKLE_UPDATER_APP"'
    copied_helper_validate = 'xcrun stapler validate "$sparkle_updater_smoke_app"'
    copied_helper_policy = 'xcrun syspolicy_check distribution "$sparkle_updater_smoke_app"'
    host_staple = 'xcrun stapler staple "$APP_PATH"'

    assert helper_staple in build_script
    assert helper_validate in build_script
    assert copied_helper_validate in build_script
    assert copied_helper_policy in build_script
    assert build_script.index(helper_staple) < build_script.index(host_staple)
