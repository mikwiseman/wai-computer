#!/usr/bin/env python3
"""Validate that WaiComputer points every surface at the intended Sentry project."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

EXPECTED_STRINGS = {
    "web/next.config.ts": [
        'project: "waicomputer-web"',
        "widenClientFileUpload: true",
    ],
    "web/Dockerfile": [
        "SENTRY_RELEASE",
        "sentry_auth_token",
    ],
    "backend/docker-compose.yml": [
        "sentry_auth_token",
        "SENTRY_RELEASE",
    ],
    "android/app/build.gradle.kts": [
        'id("io.sentry.android.gradle")',
        'projectName.set("waicomputer-android")',
        "includeProguardMapping.set(true)",
        "autoUploadProguardMapping.set(true)",
        "includeSourceContext.set(true)",
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
    for relative in [
        "ios/WaiComputer/WaiComputer/App/WaiComputerApp.swift",
        "macos/WaiComputer/WaiComputer/App/WaiComputerMacApp.swift",
        "android/gradle.properties",
    ]:
        assert_no_waisay_project_ids(relative)

    for relative, expected_values in EXPECTED_STRINGS.items():
        text = read(relative)
        for expected in expected_values:
            if expected not in text:
                raise AssertionError(f"{relative} is missing {expected!r}")

    if "SENTRY_DSN" not in read("docs/observability.md"):
        raise AssertionError("docs/observability.md does not document SENTRY_DSN")


if __name__ == "__main__":
    main()
