#!/usr/bin/env bash
# Build and publish the Linux AppImage release. Runs on a Linux x64 host with
# .NET 9 SDK and Velopack CLI 0.0.1298 installed.
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "Usage: $0 {stable|beta}" >&2
  exit 64
fi

CHANNEL="$1"
case "$CHANNEL" in
  stable) VELOPACK_CHANNEL="linux" ;;
  beta) VELOPACK_CHANNEL="linux-beta" ;;
  *) echo "ERROR: channel must be 'stable' or 'beta', got '$CHANNEL'" >&2; exit 64 ;;
esac

REPO_ROOT=$(git rev-parse --show-toplevel)
cd "$REPO_ROOT"

if [[ "$(uname -s)" != "Linux" ]]; then
  echo "ERROR: Linux releases must be built on a Linux host so AppImage tooling can run." >&2
  exit 1
fi

if [[ "$(uname -m)" != "x86_64" ]]; then
  echo "ERROR: Linux v1 releases are x64-only; expected x86_64 host." >&2
  exit 1
fi

if ! command -v dotnet >/dev/null 2>&1; then
  echo "ERROR: dotnet SDK is required." >&2
  exit 1
fi

if ! command -v vpk >/dev/null 2>&1; then
  echo "ERROR: Velopack CLI 'vpk' is required. Install version 0.0.1298." >&2
  exit 1
fi

if ! vpk -H 2>/dev/null | grep -q "Velopack CLI 0.0.1298"; then
  echo "ERROR: Velopack CLI 0.0.1298 is required for deterministic Linux packaging." >&2
  exit 1
fi

VERSION=$(awk -F'[<>]' '/<Version>/{print $3; exit}' linux/Directory.Build.props)
if [[ -z "$VERSION" ]]; then
  echo "ERROR: could not read <Version> from linux/Directory.Build.props" >&2
  exit 1
fi

RELEASE_ROOT="$REPO_ROOT/artifacts/releases/linux"
RELEASE_DIR="$RELEASE_ROOT/$VERSION-$CHANNEL"
PUBLISH_DIR="$RELEASE_DIR/publish"
PACKAGE_DIR="$RELEASE_DIR/packages"
NOTES_PATH="$RELEASE_DIR/release-notes.md"

rm -rf "$RELEASE_DIR"
mkdir -p "$PUBLISH_DIR" "$PACKAGE_DIR"

cat > "$NOTES_PATH" <<EOF
# WaiComputer $VERSION Linux $CHANNEL

- Avalonia Linux desktop client.
- User-space PulseAudio/PipeWire capture through PulseAudio protocol tools.
- Secret Service session storage and XDG desktop integration.
EOF

dotnet restore linux/WaiComputer.Linux.sln
dotnet test linux/WaiComputer.Linux.Tests/WaiComputer.Linux.Tests.csproj -c Release --no-restore
dotnet publish linux/WaiComputer.Linux/WaiComputer.Linux.csproj \
  -c Release \
  -r linux-x64 \
  --self-contained true \
  --no-restore \
  -o "$PUBLISH_DIR"

"$REPO_ROOT/scripts/sentry-upload-debug-files.sh" waicomputer-linux "$PUBLISH_DIR"

vpk pack \
  --packId is.waiwai.computer \
  --packTitle WaiComputer \
  --packAuthors WaiWai \
  --packVersion "$VERSION" \
  --packDir "$PUBLISH_DIR" \
  --mainExe WaiComputer \
  --runtime linux-x64 \
  --channel "$VELOPACK_CHANNEL" \
  --icon "$REPO_ROOT/assets/app-icon-1024.png" \
  --categories "Office;AudioVideo;Utility" \
  --releaseNotes "$NOTES_PATH" \
  --outputDir "$PACKAGE_DIR"

(
  cd "$PACKAGE_DIR"
  for appimage in *.AppImage; do
    sha256sum "$appimage"
  done > SHA256SUMS
)
cat > "$PACKAGE_DIR/runtime-dependencies.txt" <<'EOF'
WaiComputer Linux runtime dependencies:

- FUSE/libfuse2 or distro-equivalent AppImage support
- PipeWire or PulseAudio with PulseAudio protocol tools (`pactl`, `parec`)
- xdg-desktop-portal backend with GNOME/KDE GlobalShortcuts, RemoteDesktop, and Clipboard portals on Wayland
- Secret Service keyring with `secret-tool`
- XDG desktop tools (`xdg-mime`)
EOF

cat > "$RELEASE_ROOT/latest-release-metadata.txt" <<EOF
version=$VERSION
channel=$CHANNEL
velopack_channel=$VELOPACK_CHANNEL
release_dir=$RELEASE_DIR
EOF

if [[ "${LINUX_RELEASE_PUBLISH:-0}" == "1" ]]; then
  VPS_HOST=${VPS_HOST:-157.180.47.68}
  VPS_USER=${VPS_USER:-}
  SSH_KEY_PATH=${SSH_KEY_PATH:-$HOME/.ssh/id_ed25519}
  REMOTE_RELEASE_ROOT=${LINUX_REMOTE_RELEASE_ROOT:-/opt/waicomputer/releases/linux}
  if [[ -z "$VPS_USER" ]]; then
    echo "ERROR: VPS_USER is required when LINUX_RELEASE_PUBLISH=1" >&2
    exit 1
  fi
  if [[ ! -f "$SSH_KEY_PATH" ]]; then
    echo "ERROR: SSH key not found at $SSH_KEY_PATH" >&2
    exit 1
  fi
  REMOTE="${VPS_USER}@${VPS_HOST}"
  SSH_OPTS=(-i "$SSH_KEY_PATH" -o BatchMode=yes -o StrictHostKeyChecking=accept-new)
  ssh "${SSH_OPTS[@]}" "$REMOTE" "install -d -m 755 '$REMOTE_RELEASE_ROOT'"
  rsync -az -e "ssh -i $SSH_KEY_PATH -o BatchMode=yes -o StrictHostKeyChecking=accept-new" \
    "$PACKAGE_DIR/" \
    "$REMOTE:$REMOTE_RELEASE_ROOT/"
fi

echo "Linux $CHANNEL AppImage release staged at $PACKAGE_DIR"
