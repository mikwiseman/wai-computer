#requires -Version 7.0
<#
.SYNOPSIS
    Bump the <Version> property in WaiComputer.csproj. Usage:
      .\sync-version-from-csproj.ps1 -NewVersion 1.0.5
#>
param(
    [Parameter(Mandatory=$true)]
    [string]$NewVersion
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$csproj = Join-Path $root "WaiComputer/WaiComputer.csproj"

$content = Get-Content $csproj -Raw
$updated = $content -replace '<Version>[\d\.\-A-Za-z]+</Version>', "<Version>$NewVersion</Version>"
if ($updated -eq $content) {
    throw "Did not find <Version> tag in $csproj"
}
$updated | Set-Content $csproj -NoNewline
Write-Host "Bumped WaiComputer.csproj <Version> to $NewVersion"
