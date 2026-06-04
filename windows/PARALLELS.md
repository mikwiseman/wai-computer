# Building WaiComputer on macOS with Parallels Desktop

The Windows client uses WinUI 3 + Windows App SDK, which build only on a
Windows host. This is the recommended setup for developing it from a Mac.

## One-time setup

### 1. Install Parallels Desktop

Parallels Desktop 20 or later. The free trial works for ~14 days; afterwards
the Standard or Pro licence is needed.

### 2. Create a Windows 11 VM

- **Apple Silicon (M-series)**: install **Windows 11 ARM64**. Parallels
  bundles the installer flow.
- **Intel Mac**: install **Windows 11 x86_64** ISO from Microsoft.

VM resources:
- 8 GB RAM minimum (16 GB recommended)
- 4 vCPUs minimum
- 80 GB disk (NTFS, expanding)
- Graphics: default (no need for "Retina mode for separate scaling")

### 3. Inside the VM, install dev tools

Open a Windows Terminal (PowerShell) and run:

```powershell
# Winget should be present on Win11; install dev tooling
winget install --id Microsoft.VisualStudio.2022.Community --override "--add Microsoft.VisualStudio.Workload.ManagedDesktop --add Microsoft.VisualStudio.Workload.NetCrossPlat --add Microsoft.VisualStudio.Component.Windows11SDK.22621 --add Microsoft.VisualStudio.ComponentGroup.WindowsAppSDK.Cs --includeRecommended"
winget install --id Microsoft.DotNet.SDK.9
winget install --id Git.Git
winget install --id Microsoft.PowerShell
winget install --id Microsoft.WindowsTerminal
```

Verify versions:

```powershell
dotnet --version       # 9.0.x
git --version
```

### 4. Share the Mac source folder into the VM

Parallels → VM → Configure → Options → Sharing:

- "Share Mac" → **On**
- "Share Mac folders with Windows" → **Home folder**
- Map to drive: **Z:** (or any letter)

In the Windows VM, the macOS path
`/Users/mikwiseman/Documents/Code/wai-computer/windows/` is now available as:

```
Z:\Users\mikwiseman\Documents\Code\wai-computer\windows\
```

or via UNC:

```
\\Mac\Home\Documents\Code\wai-computer\windows\
```

### 5. (Optional) Speed boost — native clone

The shared folder is slower than native NTFS for large file iterations. For
the inner dev loop you can keep a second clone inside the VM:

```powershell
cd C:\src
git clone <your-fork-or-origin> wai-computer
cd wai-computer\windows
```

You can `git pull` either side; Mik usually edits via Claude on the Mac and
pulls in the VM.

## Daily workflow

**Edit** (on Mac, via Claude Code or any editor):
```bash
# from Mac
cd /Users/mikwiseman/Documents/Code/wai-computer/windows
# edits via Claude Code — files visible immediately in VM
```

**Build + run** (inside Win VM):
```powershell
cd Z:\Users\mikwiseman\Documents\Code\wai-computer\windows
dotnet restore
dotnet build -c Debug
dotnet run --project WaiComputer
```

**Tests** (inside Win VM — runs every test project):
```powershell
dotnet test                                # all projects
dotnet test ../desktop/WaiComputer.Core.Tests         # portable only
dotnet test WaiComputer.Native.Tests       # Win-only
dotnet test WaiComputer.UITests            # launches the built app
```

**Coverage report**:
```powershell
dotnet test --collect:"XPlat Code Coverage"
dotnet tool install -g dotnet-reportgenerator-globaltool
reportgenerator -reports:**\coverage.cobertura.xml -targetdir:coverage -reporttypes:Html
start coverage\index.html
```

**Debug**: open `WaiComputer.sln` in Visual Studio inside the VM, F5 to launch
under debugger. Breakpoints work; XAML Hot Reload works.

## Release

The release script signs with Azure Trusted Signing and uploads to the VPS.
Run inside the VM (needs Az credentials + SSH key):

```powershell
.\scripts\release-windows.ps1 stable    # or 'beta'
```

See [`scripts/release-windows.ps1`](scripts/release-windows.ps1) for details.

## Troubleshooting

- **"WindowsAppSDK not found"** — Reinstall the VS workload:
  `Visual Studio Installer → Modify → Individual components →
  Windows App SDK C# Templates`.
- **NAudio "exception 0x80070005" on first capture** — Win11 mic privacy
  setting blocking. Open `Settings → Privacy & security → Microphone` and
  ensure "Let desktop apps access your microphone" is on.
- **Shared folder build very slow** — Move build output to a native path:
  `dotnet build -p:BaseOutputPath=C:\build\WaiComputer\` or use the
  second native clone (step 5 above).
- **VS Code on Mac to drive the Win build** — Install the
  "Remote - SSH" extension on macOS VS Code, install OpenSSH on the VM
  (`Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0;
  Start-Service sshd`), SSH from Mac → Win. Edit and build on Mac, run
  in VM.
