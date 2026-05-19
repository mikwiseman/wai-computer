#requires -Version 7.0
<#
.SYNOPSIS
    Package + sign + upload a WaiComputer Windows build via Velopack.

.DESCRIPTION
    Mirrors scripts/release-macos.sh:
      1. Bump CSPROJ Version property (or accept -Version)
      2. dotnet publish -r win-x64
      3. vpk pack with Azure Trusted Signing
      4. Merge into wai.computer/releases/windows/releases.win[.beta].json
      5. SCP to root@157.180.47.68:/opt/waicomputer/releases/windows/

.PARAMETER Channel
    "stable" or "beta". Required.
.PARAMETER Version
    SemVer for this release. Defaults to the current <Version> in WaiComputer.csproj.

.NOTES
    Required env vars:
      WAI_AZURE_TRUSTED_SIGNING_ENDPOINT
      WAI_AZURE_TRUSTED_SIGNING_ACCOUNT
      WAI_AZURE_TRUSTED_SIGNING_CERTIFICATE_PROFILE
      WAI_VPS_USER (default: root)
      WAI_VPS_HOST (default: 157.180.47.68)
#>
param(
    [Parameter(Mandatory=$true)]
    [ValidateSet("stable", "beta")]
    [string]$Channel,

    [string]$Version,

    [string]$FeedUrl = "https://wai.computer/releases/windows"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$csproj = Join-Path $root "WaiComputer/WaiComputer.csproj"

if (-not $Version) {
    $xml = [xml](Get-Content $csproj)
    $Version = $xml.Project.PropertyGroup.Version
    if (-not $Version) { throw "No <Version> in csproj and -Version not supplied." }
}

Write-Host "▶ Packaging WaiComputer $Version ($Channel)" -ForegroundColor Cyan

Push-Location $root
try {
    dotnet restore
    dotnet publish WaiComputer/WaiComputer.csproj `
        -c Release `
        -r win-x64 `
        --self-contained=false `
        -p:WindowsAppSDKSelfContained=true `
        -o publish/win-x64

    $packArgs = @(
        "pack",
        "--packId", "is.waiwai.computer",
        "--packVersion", $Version,
        "--packDir", "publish/win-x64",
        "--mainExe", "WaiComputer.exe",
        "--channel", $Channel,
        "--releaseNotes", "release-notes.md"
    )

    $tsEndpoint = $env:WAI_AZURE_TRUSTED_SIGNING_ENDPOINT
    $tsAccount = $env:WAI_AZURE_TRUSTED_SIGNING_ACCOUNT
    $tsProfile = $env:WAI_AZURE_TRUSTED_SIGNING_CERTIFICATE_PROFILE
    if ($tsEndpoint -and $tsAccount -and $tsProfile) {
        $packArgs += @(
            "--azureTrustedSigningEndpoint", $tsEndpoint,
            "--azureTrustedSigningAccount", $tsAccount,
            "--azureTrustedSigningCertificateProfile", $tsProfile
        )
    } else {
        Write-Host "⚠ Azure Trusted Signing env vars not set — building UNSIGNED" -ForegroundColor Yellow
    }

    & vpk @packArgs

    $vpsUser = if ($env:WAI_VPS_USER) { $env:WAI_VPS_USER } else { "root" }
    $vpsHost = if ($env:WAI_VPS_HOST) { $env:WAI_VPS_HOST } else { "157.180.47.68" }
    $remote = "${vpsUser}@${vpsHost}:/opt/waicomputer/releases/windows/"

    Write-Host "▶ Ensuring remote releases/windows directory exists" -ForegroundColor Cyan
    ssh "${vpsUser}@${vpsHost}" "mkdir -p /opt/waicomputer/releases/windows"

    Write-Host "▶ Uploading to $remote" -ForegroundColor Cyan
    scp -r Releases/* $remote

    Write-Host "▶ Verifying feed at $FeedUrl/releases.win.$Channel.json" -ForegroundColor Cyan
    $feedSuffix = if ($Channel -eq "beta") { ".beta" } else { "" }
    $feedUrl = "$FeedUrl/releases.win$feedSuffix.json"
    Invoke-RestMethod -Uri $feedUrl -ErrorAction Stop | Out-Null
    Write-Host "✓ Release $Version ($Channel) published" -ForegroundColor Green
}
finally {
    Pop-Location
}
