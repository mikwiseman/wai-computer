# WaiComputer for Linux

Native Linux desktop client for WaiComputer, built with Avalonia on .NET 9 and shared desktop core code from `../desktop/WaiComputer.Core`.

## Scope

Linux v1 targets x64 GNOME/KDE sessions on Ubuntu 26.04 LTS, Ubuntu 24.04 LTS, and Fedora 44. It uses only user-space desktop APIs and tools:

- PulseAudio protocol on PipeWire/PulseAudio through `pactl` and `parec`
- XDG portals for Wayland capability checks
- X11 capability path for XGrabKey/XTest-compatible sessions
- Secret Service through `secret-tool`
- XDG `.desktop` and `x-scheme-handler/waicomputer`
- Velopack AppImage feeds at `https://wai.computer/releases/linux`

No custom audio driver, privileged helper, `uinput`, `ydotool`, or root setup is part of v1.

## Projects

| Project | What |
|---|---|
| `../desktop/WaiComputer.Core` | Portable API, auth models, audio mixing, realtime sessions, recording backup, sanitizer. |
| `WaiComputer.Linux` | Avalonia desktop app and Linux-native platform services. |
| `WaiComputer.Linux.Tests` | Linux unit tests for audio source parsing, capability gates, Secret Service behavior, update channels, hotkey/text insertion decisions, and URL handling. |

## Local Dev

```bash
cd linux
dotnet restore WaiComputer.Linux.sln
dotnet test WaiComputer.Linux.Tests
dotnet run --project WaiComputer.Linux
```

Runtime dependencies for full local behavior:

```bash
pactl info
pactl list short sources
parec --version
busctl --user list
secret-tool --help
xdg-mime --version
```

System audio is available only when `pactl list short sources` exposes a monitor source for the active sink. Missing monitor source is surfaced as unsupported; the app does not silently downgrade a requested mic+system recording to mic-only.

## Release

Install .NET 9 SDK and Velopack CLI `0.0.1298` on a Linux x64 host, then:

```bash
scripts/release-linux.sh stable
scripts/release-linux.sh beta
```

By default the script stages packages under `artifacts/releases/linux/<version>-<channel>/packages`. To publish to the VPS release directory, set `LINUX_RELEASE_PUBLISH=1 VPS_USER=root`.
