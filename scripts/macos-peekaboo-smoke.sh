#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PEEKABOO_BIN="${PEEKABOO_BIN:-peekaboo}"
DERIVED_DATA_PATH="${DERIVED_DATA_PATH:-/tmp/wai-computer-peekaboo-dd}"
ARTIFACT_ROOT="${ARTIFACT_ROOT:-$ROOT_DIR/artifacts/peekaboo/macos-smoke}"
RUN_ID="${RUN_ID:-$(date +%Y%m%d-%H%M%S)}"
RUN_DIR="$ARTIFACT_ROOT/$RUN_ID"
APP_PATH="${WAICOMPUTER_MAC_APP_PATH:-$DERIVED_DATA_PATH/Build/Products/Debug/WaiComputer.app}"
BUILD_APP="${WAICOMPUTER_PEEKABOO_BUILD:-}"
KEEP_APP_OPEN="${WAICOMPUTER_PEEKABOO_KEEP_APP_OPEN:-0}"

if [[ -z "$BUILD_APP" ]]; then
  if [[ -n "${WAICOMPUTER_MAC_APP_PATH:-}" ]]; then
    BUILD_APP=0
  else
    BUILD_APP=1
  fi
fi

mkdir -p "$RUN_DIR"
ORIGINAL_ENV_DIR="$RUN_DIR/original-launch-env"
mkdir -p "$ORIGINAL_ENV_DIR"

TARGET_BUNDLE_ID=""
TARGET_APP_REF=""
TARGET_WINDOW_ID=""

log() {
  printf '[peekaboo-smoke] %s\n' "$*" >&2
}

die() {
  printf '[peekaboo-smoke] ERROR: %s\n' "$*" >&2
  printf '[peekaboo-smoke] artifacts: %s\n' "$RUN_DIR" >&2
  exit 1
}

peekaboo() {
  command "$PEEKABOO_BIN" "$@"
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || die "Missing required command: $1"
}

remember_launch_env() {
  local key="$1"
  if [[ ! -f "$ORIGINAL_ENV_DIR/$key" ]]; then
    launchctl getenv "$key" > "$ORIGINAL_ENV_DIR/$key" 2>/dev/null || true
  fi
}

set_launch_env() {
  local key="$1"
  local value="$2"
  remember_launch_env "$key"
  launchctl setenv "$key" "$value"
}

unset_launch_env() {
  local key="$1"
  remember_launch_env "$key"
  launchctl unsetenv "$key" || true
}

restore_launch_env() {
  local key value file
  for file in "$ORIGINAL_ENV_DIR"/*; do
    [[ -e "$file" ]] || return 0
    key="$(basename "$file")"
    value="$(cat "$file")"
    if [[ -n "$value" ]]; then
      launchctl setenv "$key" "$value" || true
    else
      launchctl unsetenv "$key" || true
    fi
  done
}

cleanup() {
  local exit_code=$?
  restore_launch_env
  if [[ "$KEEP_APP_OPEN" != "1" && -n "$TARGET_BUNDLE_ID" ]]; then
    quit_target_apps "$TARGET_BUNDLE_ID" >/dev/null 2>&1 || true
  fi
  exit "$exit_code"
}
trap cleanup EXIT

assert_peekaboo_version() {
  local version_output version major minor patch
  version_output="$(peekaboo --version)"
  printf '%s\n' "$version_output" > "$RUN_DIR/peekaboo-version.txt"
  log "$version_output"

  if [[ "$version_output" =~ (alpha|beta|rc) ]] && [[ "${WAICOMPUTER_ALLOW_PEEKABOO_PRERELEASE:-0}" != "1" ]]; then
    die "Peekaboo prerelease builds are not accepted for the smoke gate: $version_output"
  fi

  version="$(printf '%s\n' "$version_output" | sed -E 's/^Peekaboo ([0-9]+)\.([0-9]+)\.([0-9]+).*/\1 \2 \3/')"
  read -r major minor patch <<< "$version"
  if [[ -z "${major:-}" || -z "${minor:-}" || -z "${patch:-}" ]]; then
    die "Unable to parse Peekaboo version from: $version_output"
  fi
  if (( major < 3 )); then
    die "Peekaboo 3.0.0 or newer is required; found $version_output"
  fi
}

assert_peekaboo_permissions() {
  local permissions_json="$RUN_DIR/peekaboo-permissions.json"
  peekaboo permissions status --json > "$permissions_json"
  jq -e '
    (.data.permissions // .permissions) as $permissions
    | ($permissions != null)
    and all($permissions[]; (.isRequired == false) or (.isGranted == true))
  ' "$permissions_json" >/dev/null || {
    cat "$permissions_json" >&2
    die "Peekaboo permissions are not fully granted"
  }
}

clean_peekaboo_snapshots() {
  local name="$1"
  peekaboo clean --all-snapshots --json > "$RUN_DIR/clean-snapshots-$name.json"
}

build_app() {
  if [[ "$BUILD_APP" != "1" ]]; then
    [[ -d "$APP_PATH" ]] || die "WAICOMPUTER_MAC_APP_PATH does not exist: $APP_PATH"
    return
  fi

  log "Building Debug macOS app for Peekaboo smoke..."
  xcodebuild \
    -project "$ROOT_DIR/macos/WaiComputer/WaiComputer.xcodeproj" \
    -scheme WaiComputer \
    -configuration Debug \
    -destination 'platform=macOS' \
    -derivedDataPath "$DERIVED_DATA_PATH" \
    CODE_SIGNING_ALLOWED=NO \
    build 2>&1 | tee "$RUN_DIR/xcodebuild-build.log"

  [[ -d "$APP_PATH" ]] || die "Built app not found at $APP_PATH"
}

read_bundle_id() {
  /usr/libexec/PlistBuddy -c 'Print :CFBundleIdentifier' "$APP_PATH/Contents/Info.plist"
}

target_pids() {
  local bundle_id="$1"
  peekaboo list apps --json \
    | jq -r --arg bundle_id "$bundle_id" '
        .data.applications[]?
        | select(.bundleIdentifier == $bundle_id)
        | .processIdentifier
      '
}

quit_target_apps() {
  local bundle_id="$1"
  local pids

  for _ in 1 2 3 4 5; do
    pids="$(target_pids "$bundle_id" | tr '\n' ' ')"
    [[ -n "${pids// }" ]] || return 0
    peekaboo app quit --app "$bundle_id" --force --json > "$RUN_DIR/quit-$bundle_id.json" || true
    sleep 0.4
  done

  pids="$(target_pids "$bundle_id" | tr '\n' ' ')"
  [[ -z "${pids// }" ]] || die "Unable to quit existing $bundle_id processes: $pids"
}

launch_fixture_app() {
  local scenario="$1"
  local language="$2"
  local permission_mock="${3:-}"
  local force_onboarding="${4:-0}"

  quit_target_apps "$TARGET_BUNDLE_ID"
  clean_peekaboo_snapshots "before-$scenario"

  set_launch_env WAI_ENABLE_UI_TEST_MODE 1
  set_launch_env UITEST_SCENARIO "$scenario"
  set_launch_env WAI_DISABLE_STORED_SESSION_RESTORE 1

  if [[ "$force_onboarding" == "1" ]]; then
    set_launch_env WAI_FORCE_ONBOARDING 1
    unset_launch_env WAI_SKIP_ONBOARDING
  else
    set_launch_env WAI_SKIP_ONBOARDING 1
    unset_launch_env WAI_FORCE_ONBOARDING
  fi

  if [[ -n "$permission_mock" ]]; then
    set_launch_env WAI_MOCK_DICTATION_PERMISSIONS "$permission_mock"
  else
    unset_launch_env WAI_MOCK_DICTATION_PERMISSIONS
  fi

  log "Launching $TARGET_BUNDLE_ID in $scenario fixture mode..."
  open -n "$APP_PATH" --args -ApplePersistenceIgnoreState YES -waiUserLanguage "$language"
  wait_for_app_running "$TARGET_BUNDLE_ID"
  TARGET_APP_REF="PID:$(target_pids "$TARGET_BUNDLE_ID" | tail -n 1)"
  refresh_target_window_id "$scenario"
  peekaboo window focus --window-id "$TARGET_WINDOW_ID" --bring-to-current-space --json > "$RUN_DIR/focus-$scenario.json" || true
  peekaboo window set-bounds --window-id "$TARGET_WINDOW_ID" --x 80 --y 80 --width 1220 --height 708 --json \
    > "$RUN_DIR/window-$scenario.json"
  sleep 0.8
}

refresh_target_window_id() {
  local name="$1"
  local windows_json="$RUN_DIR/windows-$name.json"
  local deadline=$((SECONDS + 20))

  while (( SECONDS < deadline )); do
    peekaboo list windows --app "$TARGET_APP_REF" --include-details bounds,ids --json > "$windows_json"
    TARGET_WINDOW_ID="$(jq -r '
      first(
        .data.windows[]?
        | select(.title == "WaiComputer")
        | select((.bounds[1][0] // 0) > 500)
        | .windowID
      ) // ""
    ' "$windows_json")"
    [[ -n "$TARGET_WINDOW_ID" ]] && return 0
    sleep 0.5
  done

  cat "$windows_json" >&2
  die "Unable to find WaiComputer main window for $TARGET_APP_REF"
}

wait_for_app_running() {
  local bundle_id="$1"
  local deadline=$((SECONDS + 20))

  while (( SECONDS < deadline )); do
    if [[ -n "$(target_pids "$bundle_id")" ]]; then
      return 0
    fi
    sleep 0.5
  done

  die "Timed out waiting for $bundle_id to launch"
}

capture_ui() {
  local name="$1"
  local json_path="$RUN_DIR/$name.json"
  local image_path="$RUN_DIR/$name.png"

  peekaboo see --window-id "$TARGET_WINDOW_ID" --json --annotate --path "$image_path" > "$json_path"
  jq -e '.success == true' "$json_path" >/dev/null || {
    cat "$json_path" >&2
    die "Peekaboo capture failed: $name"
  }
  printf '%s\n' "$json_path"
}

ui_contains() {
  local json_path="$1"
  local needle="$2"
  jq -e --arg needle "$needle" '
    ($needle | ascii_downcase) as $expected
    | (.data.ui_elements // [])
    | any(.[]; (
        [
          .id,
          .identifier,
          .label,
          .title,
          .description,
          .value,
          .help,
          .role,
          .role_description
        ]
        | map(select(type == "string"))
        | join(" ")
        | ascii_downcase
        | contains($expected)
      ))
  ' "$json_path" >/dev/null
}

wait_for_ui_text() {
  local name="$1"
  local needle="$2"
  local deadline=$((SECONDS + 15))
  local json_path

  while (( SECONDS < deadline )); do
    json_path="$(capture_ui "$name")"
    if ui_contains "$json_path" "$needle"; then
      log "Found UI marker '$needle' in $name"
      printf '%s\n' "$json_path"
      return 0
    fi
    sleep 0.8
  done

  json_path="$(capture_ui "$name-timeout")"
  cat "$json_path" >&2
  die "Timed out waiting for UI marker '$needle'"
}

element_id_by_identifier() {
  local json_path="$1"
  local identifier="$2"
  jq -r --arg identifier "$identifier" '
    first(
      .data.ui_elements[]?
      | select(.identifier == $identifier)
      | .id
    ) // ""
  ' "$json_path"
}

element_id_by_label() {
  local json_path="$1"
  local label="$2"
  jq -r --arg label "$label" '
    first(
      .data.ui_elements[]?
      | select((.label // "") == $label or (.description // "") == $label)
      | .id
    ) // ""
  ' "$json_path"
}

element_id_by_identifier_label_role() {
  local json_path="$1"
  local identifier="$2"
  local label="$3"
  local role="$4"
  jq -r --arg identifier "$identifier" --arg label "$label" --arg role "$role" '
    ($role | ascii_downcase) as $expectedRole
    | first(
        .data.ui_elements[]?
        | select(.identifier == $identifier)
        | select((.label // "") == $label or (.description // "") == $label)
        | select(((.role_description // .role // "") | ascii_downcase | contains($expectedRole)))
        | .id
      ) // ""
  ' "$json_path"
}

snapshot_id() {
  jq -r '.data.snapshot_id' "$1"
}

element_center_coords() {
  local json_path="$1"
  local element_id="$2"
  jq -r --arg element_id "$element_id" '
    (.data.observation.target.bounds[0][0] // 0) as $originX
    | (.data.observation.target.bounds[0][1] // 0) as $originY
    | first(
      .data.ui_elements[]?
      | select(.id == $element_id)
      | "\(((.bounds.x - $originX) + (.bounds.width / 2)) | floor),\(((.bounds.y - $originY) + (.bounds.height / 2)) | floor)"
    ) // ""
  ' "$json_path"
}

click_element() {
  local json_path="$1"
  local element_id="$2"
  local name="$3"
  local coords

  [[ -n "$element_id" && "$element_id" != "null" ]] || die "Missing element id for $name"
  coords="$(element_center_coords "$json_path" "$element_id")"
  [[ -n "$coords" && "$coords" != "null" ]] || die "Missing coordinates for $name ($element_id)"
  peekaboo window focus --window-id "$TARGET_WINDOW_ID" --bring-to-current-space --json > "$RUN_DIR/focus-before-$name.json" || true
  if ! peekaboo click --coords "$coords" --window-id "$TARGET_WINDOW_ID" --no-auto-focus --bring-to-current-space --wait-for 5000 --json \
    > "$RUN_DIR/click-$name.json"; then
    cat "$RUN_DIR/click-$name.json" >&2
    die "Click command failed: $name"
  fi
  jq -e '.success == true' "$RUN_DIR/click-$name.json" >/dev/null || {
    cat "$RUN_DIR/click-$name.json" >&2
    die "Click failed: $name"
  }
}

click_identifier() {
  local json_path="$1"
  local identifier="$2"
  local element_id

  element_id="$(element_id_by_identifier "$json_path" "$identifier")"
  click_element "$json_path" "$element_id" "$identifier"
}

click_query() {
  local query="$1"
  local name="$2"
  local json_path fresh_snapshot

  peekaboo app switch --to "$TARGET_APP_REF" --json > "$RUN_DIR/switch-before-$name.json" || true
  peekaboo window focus --window-id "$TARGET_WINDOW_ID" --bring-to-current-space --json > "$RUN_DIR/focus-before-$name.json" || true
  json_path="$(capture_ui "before-click-$name")"
  fresh_snapshot="$(snapshot_id "$json_path")"
  [[ -n "$fresh_snapshot" && "$fresh_snapshot" != "null" ]] || die "Missing Peekaboo snapshot id before click: $name"

  if ! peekaboo click "$query" --snapshot "$fresh_snapshot" --window-id "$TARGET_WINDOW_ID" --bring-to-current-space --wait-for 5000 --json \
    > "$RUN_DIR/click-$name.json"; then
    cat "$RUN_DIR/click-$name.json" >&2
    die "Click command failed: $name"
  fi
  jq -e '.success == true' "$RUN_DIR/click-$name.json" >/dev/null || {
    cat "$RUN_DIR/click-$name.json" >&2
    die "Click failed: $name"
  }
}

press_key() {
  local key="$1"
  local name="$2"

  if ! peekaboo press "$key" --app "$TARGET_APP_REF" --json > "$RUN_DIR/press-$name.json"; then
    cat "$RUN_DIR/press-$name.json" >&2
    die "Key press failed: $name"
  fi
}

run_main_search_smoke() {
  local json_path

  launch_fixture_app main_view en
  json_path="$(wait_for_ui_text main-ready "All Recordings")"
  ui_contains "$json_path" "sidebar-settings" || die "Settings sidebar item missing"
  ui_contains "$json_path" "import-audio-button" || die "Import button missing"

  click_query "Search" sidebar-search
  json_path="$(wait_for_ui_text search-ready "Search recordings")"
  click_query "Search recordings..." search-field
  if ! peekaboo type "search" --app "$TARGET_APP_REF" --profile linear --delay 0 --json \
    > "$RUN_DIR/type-search-query.json"; then
    cat "$RUN_DIR/type-search-query.json" >&2
    die "Typing search query failed"
  fi

  json_path="$(capture_ui search-query-entered)"
  ui_contains "$json_path" "Search" || die "Search submit button missing"
  press_key return search-submit
  json_path="$(wait_for_ui_text search-results "Weekly Team Standup")"
  ui_contains "$json_path" "%" && die "Search result should not expose a percent relevance score"

  click_query "Weekly Team Standup" search-result-row
  wait_for_ui_text search-result-detail "Good morning everyone"
}

run_recording_flow_smoke() {
  local json_path

  launch_fixture_app recording_flow en
  json_path="$(wait_for_ui_text recording-flow-ready "Record")"
  click_query "Record" start-recording-button

  json_path="$(wait_for_ui_text recording-flow-live "UI test live transcript")"
  click_query "Stop" stop-recording-button
  wait_for_ui_text recording-flow-detail "UI test finalized transcript."
}

main() {
  require_command jq
  if [[ "$BUILD_APP" == "1" ]]; then
    require_command xcodebuild
  fi
  require_command "$PEEKABOO_BIN"
  require_command launchctl
  require_command open

  assert_peekaboo_version
  assert_peekaboo_permissions
  clean_peekaboo_snapshots start
  build_app

  TARGET_BUNDLE_ID="$(read_bundle_id)"
  [[ -n "$TARGET_BUNDLE_ID" ]] || die "Unable to read app bundle id"
  log "Target app: $APP_PATH ($TARGET_BUNDLE_ID)"

  run_main_search_smoke
  run_recording_flow_smoke

  log "Peekaboo macOS smoke passed"
  log "Artifacts: $RUN_DIR"
}

main "$@"
