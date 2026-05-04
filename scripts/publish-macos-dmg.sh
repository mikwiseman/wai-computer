#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "$0")/.." && pwd)
RELEASE_ROOT=${MACOS_RELEASE_ROOT:-"$ROOT_DIR/artifacts/releases/macos"}
REMOTE_RELEASE_ROOT=${MACOS_REMOTE_RELEASE_ROOT:-/opt/waisay/releases/macos}
VPS_HOST=${VPS_HOST:-157.180.47.68}
VPS_USER=${VPS_USER:-}
SSH_KEY_PATH=${SSH_KEY_PATH:-$HOME/.ssh/id_ed25519}

if [[ -z "$VPS_USER" ]]; then
  echo "ERROR: VPS_USER is required" >&2
  exit 1
fi

if [[ ! -f "$SSH_KEY_PATH" ]]; then
  echo "ERROR: SSH key not found at $SSH_KEY_PATH" >&2
  exit 1
fi

METADATA_PATH="$RELEASE_ROOT/latest-release-metadata.txt"
if [[ ! -f "$METADATA_PATH" ]]; then
  echo "ERROR: latest release metadata not found at $METADATA_PATH. Run scripts/build-macos-dmg.sh first." >&2
  exit 1
fi

VERSION=$(awk -F= '$1 == "version" {print $2}' "$METADATA_PATH")
BUILD=$(awk -F= '$1 == "build" {print $2}' "$METADATA_PATH")
if [[ -z "$VERSION" || -z "$BUILD" ]]; then
  echo "ERROR: release metadata is missing version or build" >&2
  exit 1
fi

RELEASE_DIR="$RELEASE_ROOT/${VERSION}-${BUILD}"
if [[ ! -d "$RELEASE_DIR" ]]; then
  echo "ERROR: release directory not found at $RELEASE_DIR" >&2
  exit 1
fi

if [[ ! -f "$RELEASE_ROOT/appcast.xml" ]]; then
  echo "ERROR: appcast not found at $RELEASE_ROOT/appcast.xml" >&2
  exit 1
fi

REMOTE="${VPS_USER}@${VPS_HOST}"
SSH_OPTS=(-i "$SSH_KEY_PATH" -o BatchMode=yes -o StrictHostKeyChecking=accept-new)

ssh "${SSH_OPTS[@]}" "$REMOTE" "install -d -m 755 '$REMOTE_RELEASE_ROOT' '$REMOTE_RELEASE_ROOT/${VERSION}-${BUILD}'"
rsync -az -e "ssh -i $SSH_KEY_PATH -o BatchMode=yes -o StrictHostKeyChecking=accept-new" \
  "$RELEASE_DIR/" \
  "$REMOTE:$REMOTE_RELEASE_ROOT/${VERSION}-${BUILD}/"
rsync -az -e "ssh -i $SSH_KEY_PATH -o BatchMode=yes -o StrictHostKeyChecking=accept-new" \
  "$RELEASE_ROOT/appcast.xml" \
  "$RELEASE_ROOT/release-notes.md" \
  "$RELEASE_ROOT/WaiSay-latest.dmg" \
  "$RELEASE_ROOT/WaiSay-latest.dmg.sha256" \
  "$RELEASE_ROOT/latest-release-metadata.txt" \
  "$REMOTE:$REMOTE_RELEASE_ROOT/"

echo "Published WaiSay ${VERSION} (${BUILD}) to $REMOTE:$REMOTE_RELEASE_ROOT"
