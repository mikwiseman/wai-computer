#!/usr/bin/env bash
set -euo pipefail

APP_IDS=(
  "is.waiwai.computer"
  "is.waiwai.computer.dev"
)

APP_NAMES=(
  "WaiComputer"
)

remove_path() {
  local path=$1
  if [[ -e "$path" ]]; then
    rm -rf "$path"
    printf 'Removed %s\n' "$path"
  fi
}

pkill -x WaiComputer || true
killall cfprefsd >/dev/null 2>&1 || true

for app_id in "${APP_IDS[@]}"; do
  defaults delete "$app_id" >/dev/null 2>&1 || true
  remove_path "$HOME/Library/Preferences/${app_id}.plist"
  remove_path "$HOME/Library/Preferences/ByHost/${app_id}."*
  remove_path "$HOME/Library/Caches/${app_id}"
  remove_path "$HOME/Library/HTTPStorages/${app_id}"
  remove_path "$HOME/Library/Saved Application State/${app_id}.savedState"
done

for app_name in "${APP_NAMES[@]}"; do
  remove_path "$HOME/Library/Caches/${app_name}"
  remove_path "$HOME/Library/HTTPStorages/${app_name}"
done

killall cfprefsd >/dev/null 2>&1 || true

echo "macOS WaiComputer local state reset complete."
