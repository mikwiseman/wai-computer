#!/usr/bin/env bash
# Build a signed macOS release locally on a Mac and publish it to the VPS.
#
# Usage:
#   scripts/release-macos.sh stable        # publish to everyone
#   scripts/release-macos.sh beta          # publish only to opted-in users
#
# Pre-flight: bump CURRENT_PROJECT_VERSION in macos/WaiComputer/project.yml and
# regenerate the xcodeproj (cd macos/WaiComputer && xcodegen generate). This
# script does not use GitHub Actions; it requires a macOS host with Xcode,
# Developer ID signing, Sparkle signing, and App Store Connect notarization
# credentials configured locally.
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "Usage: $0 {stable|beta}" >&2
  exit 64
fi

CHANNEL="$1"
case "$CHANNEL" in
  stable|beta) ;;
  *) echo "ERROR: channel must be 'stable' or 'beta', got '$CHANNEL'" >&2; exit 64 ;;
esac

REPO_ROOT=$(git rev-parse --show-toplevel)
cd "$REPO_ROOT"

if [[ -n "$(git status --porcelain)" ]]; then
  echo "WARNING: working tree has uncommitted changes; local release will include them." >&2
fi

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "ERROR: macOS releases require a Mac build host with xcodebuild." >&2
  exit 1
fi

if ! command -v xcodebuild >/dev/null 2>&1; then
  echo "ERROR: xcodebuild is required for macOS release builds." >&2
  exit 1
fi

VARIANTS=("global" "ru")
if [[ -n "${MACOS_VARIANT:-}" ]]; then
  VARIANTS=("$MACOS_VARIANT")
fi

for variant in "${VARIANTS[@]}"; do
  echo "Building notarized macOS DMG locally with channel=$CHANNEL variant=$variant ..."
  MACOS_RELEASE_STRICT=1 \
    RELEASE_CHANNEL="$CHANNEL" \
    MACOS_VARIANT="$variant" \
    scripts/build-macos-dmg.sh
done
echo "Publishing macOS artifacts to wai.computer ..."
scripts/publish-macos-dmg.sh
