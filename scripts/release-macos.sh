#!/usr/bin/env bash
# Trigger a macOS release through GitHub Actions.
#
# Usage:
#   scripts/release-macos.sh stable        # publish to everyone
#   scripts/release-macos.sh beta          # publish only to opted-in users
#
# Pre-flight: bump CURRENT_PROJECT_VERSION in macos/WaiComputer/project.yml,
# regenerate the xcodeproj (cd macos/WaiComputer && xcodegen generate),
# commit, and push BEFORE running this script. The CI build uses HEAD on
# the main branch, so unpushed commits will not be included.
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

if ! command -v gh >/dev/null 2>&1; then
  echo "ERROR: gh (GitHub CLI) is required" >&2
  exit 1
fi

REPO_ROOT=$(git rev-parse --show-toplevel)
cd "$REPO_ROOT"

if [[ -n "$(git status --porcelain)" ]]; then
  echo "WARNING: working tree has uncommitted changes; CI will build from the last pushed commit on main." >&2
fi

LOCAL_HEAD=$(git rev-parse HEAD)
REMOTE_HEAD=$(git rev-parse origin/main 2>/dev/null || echo "")
if [[ -n "$REMOTE_HEAD" && "$LOCAL_HEAD" != "$REMOTE_HEAD" ]]; then
  echo "WARNING: local HEAD ($LOCAL_HEAD) differs from origin/main ($REMOTE_HEAD); CI builds from origin/main." >&2
fi

echo "Triggering macOS Direct Release on main with channel=$CHANNEL ..."
gh workflow run "macOS Direct Release" --ref main \
  -f release_channel="$CHANNEL" \
  -f publish_web=true

sleep 3
gh run list --limit 1 --workflow="macOS Direct Release"
