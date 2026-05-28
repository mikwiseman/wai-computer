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

# Fail FAST on the missing-Sentry-token case. dSYM upload happens AFTER the
# 5-10 min xcodebuild archive completes, so a missing token used to surface
# only after the build had already burned 5+ minutes — and worse, would
# leave a notarized DMG without the appcast updated, so the release looked
# successful but users never got the update. Try to self-load from
# 1Password when the env var is empty AND `op` is available; otherwise
# fail upfront with a copy-pasteable command.
if [[ -z "${SENTRY_AUTH_TOKEN:-}" ]]; then
  if command -v op >/dev/null 2>&1; then
    echo "SENTRY_AUTH_TOKEN not set — attempting 1Password self-load…"
    if SENTRY_AUTH_TOKEN_LOADED=$(op read "op://<vault>/Sentry WaiComputer/password" 2>/dev/null) \
       && [[ -n "$SENTRY_AUTH_TOKEN_LOADED" ]]; then
      export SENTRY_AUTH_TOKEN="$SENTRY_AUTH_TOKEN_LOADED"
      unset SENTRY_AUTH_TOKEN_LOADED
      echo "✓ Loaded SENTRY_AUTH_TOKEN from 1Password (op://<vault>/Sentry WaiComputer)"
    fi
  fi
  if [[ -z "${SENTRY_AUTH_TOKEN:-}" ]]; then
    echo "ERROR: SENTRY_AUTH_TOKEN is required for the macOS release dSYM upload." >&2
    echo "       Without it, xcodebuild + notarization will succeed but" >&2
    echo "       sentry-upload-debug-files.sh will fail mid-pipeline AFTER" >&2
    echo "       ~5 minutes of compile time, and the appcast will NOT be updated." >&2
    echo "" >&2
    echo "       Set it before running this script:" >&2
    echo "" >&2
    echo "         export SENTRY_AUTH_TOKEN=\$(op read 'op://<vault>/Sentry WaiComputer/password')" >&2
    echo "         VPS_USER=<release-user> scripts/release-macos.sh $CHANNEL" >&2
    echo "" >&2
    exit 1
  fi
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
