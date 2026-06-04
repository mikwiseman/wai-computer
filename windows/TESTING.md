# Windows v1.0 — Test Plan & Manual QA

Mirror of the macOS testing playbook, adapted for Windows specifics.

## Automated layers

| Layer | Project | Where | Coverage gate |
|---|---|---|---|
| Unit | `WaiComputer.Core.Tests` | Any OS with .NET 9 SDK | ≥ 85% line |
| Native | `WaiComputer.Native.Tests` | Win-only | ≥ 70% line |
| UI | `WaiComputer.UITests` | Win-only (FlaUI) | Smoke-only, not gated |
| Perf | `WaiComputer.Bench` | Any OS | Run on every release tag |

Run them all locally:

```powershell
cd windows
.\scripts\qa-loop.ps1
```

Run just the portable suite (works from macOS via `dotnet test` if you've
installed the .NET 9 SDK on the Mac side):

```bash
cd windows
dotnet test ../desktop/WaiComputer.Core.Tests/WaiComputer.Core.Tests.csproj
```

## Manual QA checklist (must all pass before promotion to stable)

### Install + first run

- [ ] `WaiComputer-Setup.exe` runs without elevation prompt on a fresh Win10
      1809 VM and a fresh Win11 24H2 VM.
- [ ] SmartScreen shows "Verified publisher: WaiWai" (Azure Trusted Signing).
- [ ] First launch opens onboarding (Welcome → Value props → Hotkey →
      Languages → Permission → Dictation sandbox).
- [ ] Onboarding "Open privacy settings" deep-links to
      `ms-settings:privacy-microphone`.
- [ ] If mic privacy is off, the permission slide shows the orange warning
      InfoBar; turning the setting on flips the bar to green within ~2 s.

### Authentication

- [ ] Sign in with magic link from Gmail in Edge.
- [ ] Magic-link click on a *running* WaiComputer focuses the existing window
      (no second instance opens).
- [ ] Token refresh works: kill the network for 30 s during an idle session,
      restore, then make a request — succeeds without re-login.
- [ ] Sign out clears `%APPDATA%\WaiComputer\session.json` and routes back
      to the auth screen.
- [ ] Delete account cascades: server account gone + local data wiped.

### Recording

- [ ] **Mic-only**: start, speak, stop. Recording appears in library with
      transcript within ~5 s of stop.
- [ ] **Dual (mic + system)**: start during a Zoom call. Both voices are
      captured. Speaker diarisation labels them as two distinct speakers.
- [ ] **Live transcript** in the recording HUD shows interim partials within
      ~500 ms of speaking; final segments within ~2 s.
- [ ] **System audio stall**: pull the audio output cable (or disable the
      render device) mid-recording → orange warning banner appears within 3 s;
      mic-only continues recording cleanly.
- [ ] **Network drop during recording**: kill wifi mid-recording. Pending
      backup goes to `%APPDATA%\WaiComputer\PendingTranscripts\{id}\`. Restore
      wifi → upload resumes, recording shows up in library.
- [ ] **App crash during recording** (kill via Task Manager): on restart,
      the pending backup is visible in library with "Pending upload" status.
      Upload retry succeeds.

### Dictation

- [ ] Press-and-hold **RightAlt** in:
  - [ ] Notepad — text appears at caret
  - [ ] VS Code editor — text appears at caret
  - [ ] Edge address bar — text appears
  - [ ] Excel cell — text appears
  - [ ] Slack message box — text appears
  - [ ] Discord chat box — text appears
  - [ ] Microsoft Teams chat — text appears
- [ ] **Double-tap** RightAlt → enters hands-free mode (HUD stays open,
      streams transcript until next tap).
- [ ] **Press another key during hold** (e.g., type Tab while holding RightAlt) →
      dictation is cancelled, no garbage text is inserted.
- [ ] **Modifier stuck** edge case: hold Ctrl + RightAlt, release RightAlt
      while still holding Ctrl. Within 500 ms of releasing Ctrl, paste fires
      and text appears. (If you keep Ctrl held > 500 ms, error banner shows
      "Text is on your clipboard — press Ctrl+V.")

### Beta channel + updates

- [ ] Settings → Updates → toggle "Receive beta updates" → "Check for updates"
      hits `releases.win.beta.json`.
- [ ] Drop a higher-version beta build into the beta feed → app downloads +
      restarts at new version. Session preserved across restart.
- [ ] Revert toggle to stable → next check uses `releases.win.json`.

### MCP

- [ ] Settings → MCP shows `https://wai.computer/mcp`.
- [ ] "Copy URL" places the URL on the clipboard.
- [ ] Per-client copy buttons place the right snippet for Claude.ai, Cursor,
      ChatGPT, Claude Code, Codex CLI.
- [ ] Paste the URL into Claude.ai → connect → Claude can list recent
      recordings via the WaiComputer MCP tools.

### Tray + lifecycle

- [ ] Tray icon present after launch.
- [ ] Tray icon changes (red dot / waveform) during active recording.
- [ ] Right-click tray → context menu shows "New recording", "Open
      WaiComputer", "Settings", "Quit".
- [ ] Closing the main window keeps the tray icon (app stays running).
- [ ] Quit via tray → process exits within 2 s, hotkey hook released.

### Observability

- [ ] Force a 500 response from the API (e.g., mock via Charles/Fiddler) →
      Sentry event captured with sanitised path and no PII (email, token,
      transcript).
- [ ] Repeat the same 500 within 5 minutes → only the first hits Sentry as an
      event; second is a breadcrumb (dedup).
- [ ] Sign in → Sentry user context has the user ID.
- [ ] Sign out → Sentry user context cleared.

### Edge cases

- [ ] High-DPI: 4K display at 200% scaling — UI is crisp, no pixel rounding
      artefacts.
- [ ] Theme: light, dark, switch mid-session — colours update without restart.
- [ ] Fast user switching: switch to another Windows user, switch back → app
      still responsive, recording (if active) still ongoing.
- [ ] RDP detach + reattach: WASAPI loopback survives audio endpoint changes.

## Coverage matrix

Each macOS feature must have a Windows test that validates the same contract:

| macOS file | Windows file | Test class |
|---|---|---|
| `APIClient.swift` (token refresh coalescing) | `Core/Api/TokenRefreshCoordinator.cs` | `TokenRefreshCoordinatorTests` |
| `SessionStore.swift` | `Core/Auth/SessionStore.cs` | `SessionStoreTests` + `DpapiSessionProtectorTests` |
| `Sanitizer` in `SentryHelper.swift` | `Core/Monitoring/Sanitizer.cs` | `SanitizerTests` |
| `AudioFileWriter.swift` | `Core/Audio/AudioFileWriter.cs` | `AudioFileWriterTests` |
| `DualAudioCapture.swift` (mixer math) | `Core/Audio/AudioMixer.cs` | `AudioMixerTests` |
| `ProviderBackedRealtimeSession.swift` | `Core/Realtime/DeepgramSession.cs` | `DeepgramSessionTests` |
| `RecordingBackupStore.swift` | `Core/Recording/RecordingBackupStore.cs` | `RecordingBackupStoreTests` |
| `GlobalHotkeyManager.swift` (state machine) | `Core/Hotkey/HotkeyStateMachine.cs` | `HotkeyStateMachineTests` |
| `TextInserter.swift` | `Core/Input/TextInserter.cs` | (Win-only integration; manual + UI test) |
| `MagicLinkUrl` parsing in `MacAppState.handleIncomingURL` | `Core/Auth/MagicLinkUrl.cs` | `MagicLinkUrlTests` |
