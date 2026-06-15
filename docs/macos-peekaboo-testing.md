# macOS Peekaboo Smoke Testing

Peekaboo is the macOS UI smoke gate for flows that need a real rendered window. It replaces the XCUITest UI automation gate for macOS smoke coverage; it does not replace `WaiComputerTests` or Swift package unit tests.

The smoke gate must run in the background: it launches WaiComputer without activation, moves the test window offscreen, targets that window by id/snapshot, and avoids global click/type/focus commands.

Official docs:

- https://peekaboo.sh/
- https://peekaboo.sh/permissions.html
- https://peekaboo.sh/commands/see.html
- https://peekaboo.sh/commands/click.html

## Scope

`scripts/macos-peekaboo-smoke.sh` builds the Debug macOS app, launches it with the existing DEBUG UI fixtures, and verifies:

- Main library shell renders expected sidebar and import controls.
- Search opens, submits a fixture query, hides relevance percentages, and opens the matching recording detail.
- Recording flow starts, shows the fixture live transcript, stops, and opens the finalized recording transcript.

The script uses deterministic fixture mode:

- `WAI_ENABLE_UI_TEST_MODE=1`
- `UITEST_SCENARIO=main_view` or `recording_flow`
- `WAI_SKIP_ONBOARDING=1`
- `WAI_DISABLE_STORED_SESSION_RESTORE=1`

## Requirements

- macOS 15 or newer for the Peekaboo automation runtime. WaiComputer still targets macOS 14.2; use the normal unsigned build and unit-test gates for target compatibility.
- Peekaboo 3.x stable, not alpha/beta/rc.
- Granted Peekaboo permissions: Screen Recording, Accessibility, and Event Synthesizing.
- `jq`, `xcodebuild`, `launchctl`, and `open`.
- No other WaiComputer instance running. The script will quit the target bundle id before each fixture.

Preflight:

```bash
peekaboo --version
peekaboo permissions status --json
```

## Commands

Build Debug and run the full smoke:

```bash
./scripts/macos-peekaboo-smoke.sh
```

Run against an existing app bundle:

```bash
WAICOMPUTER_MAC_APP_PATH=/path/to/WaiComputer.app ./scripts/macos-peekaboo-smoke.sh
```

Keep the app open after a failing run:

```bash
WAICOMPUTER_PEEKABOO_KEEP_APP_OPEN=1 ./scripts/macos-peekaboo-smoke.sh
```

Artifacts are written under:

```bash
artifacts/peekaboo/macos-smoke/<run-id>/
```

Each run stores the Peekaboo version, permission JSON, xcodebuild log, window lists, captures, annotated screenshots, and click outputs. `artifacts/` is ignored by git.

## Scheme Policy

The default `WaiComputer` scheme should run `WaiComputerTests` only. `WaiComputerUITests` can stay in the project for historical reference or focused local diagnosis, but it is not part of the default macOS gate because it has been unreliable in this app.

`WaiComputerUITests` are foreground-only by design: XCUITest launches and activates the app. They are skipped unless `WAI_ALLOW_FOREGROUND_XCUITESTS=1` is set explicitly. Do not use that target for routine agent verification on Mik's machine; use `scripts/macos-peekaboo-smoke.sh` instead.

If `macos/WaiComputer/project.yml` changes, regenerate the Xcode project:

```bash
cd macos/WaiComputer && xcodegen generate
```

## Failure Rules

Do not add fallback clicks. The smoke should fail with the exact Peekaboo error and preserve artifacts.

Common deterministic fixes:

- `SNAPSHOT_NOT_FOUND`: the script must run `peekaboo see` immediately before click actions and pass the explicit snapshot id.
- Focus mismatch with another frontmost app: keep the smoke on background Peekaboo actions (`--window-id`, snapshot ids, `perform-action`, `set-value`) and fix the target-window lookup. Do not switch apps, focus windows, or silently click another app.
- Missing fixture text: fix the DEBUG fixture state or app rendering path, then rerun the smoke.
