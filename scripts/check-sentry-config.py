#!/usr/bin/env python3
"""Validate that WaiComputer points every surface at the intended Sentry project."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

EXPECTED_PROJECT_IDS = {
    "backend": "4511116051873792",
    "ios": "4511116052070400",
    "macos": "4511116051939328",
    "web": "4511421057466368",
}

EXPECTED_STRINGS = {
    "web/next.config.ts": [
        'project: "waicomputer-web"',
        "widenClientFileUpload: true",
    ],
    "web/Dockerfile": [
        "SENTRY_RELEASE",
        "sentry_auth_token",
    ],
    "web/src/instrumentation-client.ts": [
        "NEXT_PUBLIC_SENTRY_DSN",
        "Sentry.init",
    ],
    "web/src/sentry.server.config.ts": [
        "NEXT_PUBLIC_SENTRY_DSN",
        "Sentry.init",
    ],
    "web/src/sentry.edge.config.ts": [
        "NEXT_PUBLIC_SENTRY_DSN",
        "Sentry.init",
    ],
    "backend/docker-compose.yml": [
        "sentry_auth_token",
        "SENTRY_RELEASE",
    ],
    "scripts/server-build.sh": [
        "SENTRY_AUTH_TOKEN",
        "SENTRY_UPLOAD_REQUIRED",
    ],
    "scripts/deploy-api.sh": [
        "waicomputer-backend",
        "waicomputer-web",
        "sentry-release.sh",
    ],
    "scripts/build-testflight.sh": [
        "waicomputer-ios",
        "sentry-upload-debug-files.sh",
    ],
    "scripts/build-macos-dmg.sh": [
        "waicomputer-macos",
        "sentry-upload-debug-files.sh",
    ],
}


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def assert_project_id(surface: str, relative: str) -> None:
    text = read(relative)
    expected = EXPECTED_PROJECT_IDS[surface]
    if expected not in text:
        raise AssertionError(f"{relative} does not target Sentry project id {expected}")


def assert_no_waisay_project_ids(relative: str) -> None:
    text = read(relative)
    old_ids = {
        "<sentry-project-id>",
        "<sentry-project-id>",
        "<sentry-project-id>",
        "<sentry-project-id>",
    }
    found = sorted(old_id for old_id in old_ids if old_id in text)
    if found:
        raise AssertionError(f"{relative} still references waisay Sentry project ids: {', '.join(found)}")


def main() -> None:
    assert_project_id("ios", "ios/WaiComputer/WaiComputer/App/WaiComputerApp.swift")
    assert_project_id("macos", "macos/WaiComputer/WaiComputer/App/WaiComputerMacApp.swift")
    assert_project_id("web", "docs/observability.md")

    for relative in [
        "ios/WaiComputer/WaiComputer/App/WaiComputerApp.swift",
        "macos/WaiComputer/WaiComputer/App/WaiComputerMacApp.swift",
    ]:
        assert_no_waisay_project_ids(relative)

    for relative, expected_values in EXPECTED_STRINGS.items():
        text = read(relative)
        for expected in expected_values:
            if expected not in text:
                raise AssertionError(f"{relative} is missing {expected!r}")

    backend_env_pattern = re.compile(r"SENTRY_DSN=.*4511116051873792")
    if not backend_env_pattern.search(read("docs/observability.md")):
        raise AssertionError("docs/observability.md does not document the backend Sentry project")


if __name__ == "__main__":
    main()
