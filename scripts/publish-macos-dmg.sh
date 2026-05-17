#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "$0")/.." && pwd)
RELEASE_ROOT=${MACOS_RELEASE_ROOT:-"$ROOT_DIR/artifacts/releases/macos"}
REMOTE_RELEASE_ROOT=${MACOS_REMOTE_RELEASE_ROOT:-/opt/waicomputer/releases/macos}
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
RELEASE_SLUG=$(awk -F= '$1 == "release_slug" {print $2}' "$METADATA_PATH")
if [[ -z "$VERSION" || -z "$BUILD" ]]; then
  echo "ERROR: release metadata is missing version or build" >&2
  exit 1
fi
if [[ -z "$RELEASE_SLUG" ]]; then
  RELEASE_SLUG="${VERSION}-${BUILD}"
fi

RELEASE_DIR="$RELEASE_ROOT/${RELEASE_SLUG}"
if [[ ! -d "$RELEASE_DIR" ]]; then
  echo "ERROR: release directory not found at $RELEASE_DIR" >&2
  exit 1
fi

if [[ ! -f "$RELEASE_ROOT/appcast.xml" ]]; then
  echo "ERROR: appcast not found at $RELEASE_ROOT/appcast.xml" >&2
  exit 1
fi

REMOTE_APPCAST_URL=${MACOS_REMOTE_APPCAST_URL:-https://wai.computer/releases/macos/appcast.xml}
MERGE_SCRIPT="$ROOT_DIR/scripts/merge-macos-appcast.py"
if [[ ! -x "$MERGE_SCRIPT" ]]; then
  echo "ERROR: merge script not executable at $MERGE_SCRIPT" >&2
  exit 1
fi
echo "Merging local appcast with remote at $REMOTE_APPCAST_URL ..."
python3 "$MERGE_SCRIPT" \
  --local "$RELEASE_ROOT/appcast.xml" \
  --remote-url "$REMOTE_APPCAST_URL" \
  --out "$RELEASE_ROOT/appcast.xml"

REMOTE="${VPS_USER}@${VPS_HOST}"
SSH_OPTS=(-i "$SSH_KEY_PATH" -o BatchMode=yes -o StrictHostKeyChecking=accept-new)

ssh "${SSH_OPTS[@]}" "$REMOTE" "install -d -m 755 '$REMOTE_RELEASE_ROOT' '$REMOTE_RELEASE_ROOT/${RELEASE_SLUG}'"
rsync -az -e "ssh -i $SSH_KEY_PATH -o BatchMode=yes -o StrictHostKeyChecking=accept-new" \
  "$RELEASE_DIR/" \
  "$REMOTE:$REMOTE_RELEASE_ROOT/${RELEASE_SLUG}/"
rsync -az -e "ssh -i $SSH_KEY_PATH -o BatchMode=yes -o StrictHostKeyChecking=accept-new" \
  "$RELEASE_ROOT/appcast.xml" \
  "$RELEASE_ROOT/release-notes.md" \
  "$RELEASE_ROOT/WaiComputer-latest.dmg" \
  "$RELEASE_ROOT/WaiComputer-latest.dmg.sha256" \
  "$RELEASE_ROOT/latest-release-metadata.txt" \
  "$REMOTE:$REMOTE_RELEASE_ROOT/"

echo "Published WaiComputer ${VERSION} (${BUILD}) to $REMOTE:$REMOTE_RELEASE_ROOT"
