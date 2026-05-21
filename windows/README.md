# WaiComputer for Windows

Native Windows 11 / Windows 10 1809+ client for [WaiComputer](https://wai.computer).

Mirrors the macOS client's feature set: recordings (mic + system audio), live
realtime transcription, dictation with global push-to-talk hotkey, library and
search, companion chat, MCP integration, and Sparkle-equivalent auto-update via
Velopack.

## Stack

- **.NET 9** + **WinUI 3** (Windows App SDK 1.6+)
- **NAudio** for WASAPI capture + WasapiLoopbackCapture (system audio)
- **System.Net.WebSockets** for realtime transcription (ElevenLabs / OpenAI /
  Inworld / Deepgram)
- **H.NotifyIcon** for the system tray
- **Velopack** for stable + beta auto-update channels
- **Sentry** for error monitoring with PII sanitisation
- **xUnit** + **FluentAssertions** + **Moq** + **WireMock.Net** + **Verify**
  for tests; **FlaUI** for UI automation; **BenchmarkDotNet** for perf

## Projects

| Project | What |
|---|---|
| `../desktop/WaiComputer.Core` | Portable `net9.0` business logic — API client, auth, audio writers, realtime sessions, recording VM, monitoring. Builds on Win / macOS / Linux. |
| `WaiComputer` | The actual WinUI 3 app — `net9.0-windows10.0.19041.0`. Win-only. |
| `../desktop/WaiComputer.Core.Tests` | Portable unit tests. Runs on any platform with the .NET 9 SDK. |
| `WaiComputer.Native.Tests` | Tests for Windows-native impls (WASAPI / hotkey / DPAPI / Velopack). Win-only. |
| `WaiComputer.UITests` | FlaUI end-to-end tests driving the built app. Win-only. |
| `WaiComputer.Bench` | BenchmarkDotNet perf benchmarks. |

## Dev environment

Either:
- **Native Windows host** with Visual Studio 2022 17.10+ (Windows App SDK
  workload), or
- **Parallels Desktop on macOS** with a Win 11 VM — see [PARALLELS.md](PARALLELS.md).

## Quickstart

```powershell
cd windows
dotnet restore
dotnet build -c Debug
dotnet test ../desktop/WaiComputer.Core.Tests   # portable tests (also runs on Mac)
dotnet test WaiComputer.Native.Tests # Win-only
dotnet run --project WaiComputer
```

## Release

See [scripts/release-windows.ps1](scripts/release-windows.ps1) and
the top-level [`AGENTS.md`](../AGENTS.md) "Windows" section.

```powershell
.\scripts\release-windows.ps1 stable    # bumps version, packs, signs, uploads
.\scripts\release-windows.ps1 beta
```

## Code style

Mirrors the rest of the repo: no fallbacks, no silent degradation, TDD-first.
See [`AGENTS.md`](../AGENTS.md) and [`CLAUDE.md`](../CLAUDE.md) at the repo root.
