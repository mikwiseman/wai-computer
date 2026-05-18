# Self-hosted macOS runner — setup

The macOS CI and Release workflows run on a self-hosted GitHub Actions
runner because:

- Apple binaries require `xcodebuild` and `notarytool`, which only exist on
  macOS. Hetzner production is Linux and can't host them.
- GitHub-hosted macOS minutes are paid (~$0.08/min). A self-hosted runner is
  free.
- Developer ID, Sparkle EdDSA, and App Store Connect notarization credentials
  stay in the runner's keychain — never uploaded as GitHub Secrets.

This doc assumes you'll use your dev Mac as the runner. Swap in a dedicated
Mac mini later if you want builds to be unaffected by Xcode's mood when
you're actively coding.

## One-time setup

### 1. Register the runner

```bash
# Pick a working directory and unzip the runner there.
mkdir -p ~/actions-runner && cd ~/actions-runner

# Download the latest macOS arm64 runner from
# https://github.com/WaiWai-is/wai-say/settings/actions/runners/new
# (replace the URLs/version below with what GitHub shows you).
curl -o actions-runner-osx-arm64.tar.gz -L \
  https://github.com/actions/runner/releases/download/v2.319.1/actions-runner-osx-arm64-2.319.1.tar.gz
tar xzf actions-runner-osx-arm64.tar.gz

# Configure. The token below is one-time and shown on the GitHub page.
./config.sh \
  --url https://github.com/WaiWai-is/wai-say \
  --token <PASTE_TOKEN_FROM_GITHUB> \
  --name "$(scutil --get LocalHostName)" \
  --labels self-hosted,macOS \
  --work _work \
  --unattended
```

The `self-hosted,macOS` labels are what `runs-on: [self-hosted, macOS]` in
the workflows matches.

### 2. Run as a launchd service

So the runner survives logout, reboots, and Xcode crashes:

```bash
cd ~/actions-runner
./svc.sh install
./svc.sh start
./svc.sh status
```

`launchd` will keep it alive and restart it after reboots.

### 3. Verify credentials on the runner

The release workflow expects all of these to already be configured on this
Mac:

- **Developer ID Application** in the keychain:
  ```bash
  security find-identity -p basic -v | grep "Developer ID Application"
  ```
  Must show `R4A779QVVY` (WaiWai, LLC).

- **Sparkle EdDSA private key** in the keychain under account
  `is.waiwai.computer.sparkle`:
  ```bash
  security find-generic-password -a is.waiwai.computer.sparkle \
    -s "Sparkle EdDSA Private Key" 2>&1 | head -3
  ```

- **App Store Connect notarization config** at
  `~/.appstoreconnect/config.json`. Required keys: `keyId`, `issuerId`,
  `keyFilePath`.

- **SSH key for the VPS** so `scripts/publish-macos-dmg.sh` can rsync the
  DMG. Test with `ssh root@157.180.47.68 echo ok`.

If any of those are missing on the runner, the release workflow will fail
fast in the `Pre-flight check` step.

## Usage

### Every push to `main`

`macos-ci.yml` triggers automatically when files under `macos/`,
`shared/WaiComputerKit/`, or any of the macOS release scripts change. It
builds the app, runs the Swift Package tests, and the macOS unit tests —
no signing, no notarization, no publish. Failures show up as a red ❌
next to the commit on GitHub. Typical run: 3–5 minutes.

### Publishing a release

1. Bump `CURRENT_PROJECT_VERSION` in `macos/WaiComputer/project.yml`
   (monotonic — Sparkle requires every published build to have a strictly
   higher number than the previous one).
2. `cd macos/WaiComputer && xcodegen generate`.
3. Commit and push.
4. Trigger the workflow:
   - **GitHub UI:** Actions → `macOS Release` → Run workflow → pick channel.
   - **CLI:** `gh workflow run macos-release.yml -f channel=stable`.
5. Watch the run. ~10–15 minutes for a full sign + notarize + upload +
   appcast merge cycle.

## Trade-offs

- **Mac asleep = no builds.** When your laptop lid is closed the runner is
  offline and any push queues until the Mac wakes. Either keep the lid
  open while a build is running, or set `pmset -a sleep 0` for the AC
  power profile, or move to a dedicated always-on Mac mini.
- **Concurrent local work.** Heavy Xcode use can starve the runner. If
  build flakiness becomes a problem, run the runner under a separate
  macOS user account so its DerivedData / TMPDIR don't collide with
  yours.
- **Single-point-of-failure.** The runner is one machine. If you ever
  need redundancy, register a second Mac with the same labels; GitHub
  load-balances.

## Removing the runner

```bash
cd ~/actions-runner
./svc.sh stop
./svc.sh uninstall
./config.sh remove --token <PASTE_REMOVAL_TOKEN_FROM_GITHUB>
```
