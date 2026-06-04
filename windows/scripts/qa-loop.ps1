#requires -Version 7.0
<#
.SYNOPSIS
    Parity with scripts/qa-loop.sh — runs every gate for Windows-touching
    work. Exits non-zero on first failure.
#>
param(
    [switch]$PortableOnly
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Push-Location $root
try {
    Write-Host "▶ dotnet restore" -ForegroundColor Cyan
    dotnet restore

    Write-Host "▶ dotnet build -c Release" -ForegroundColor Cyan
    dotnet build WaiComputer.sln -c Release --no-restore

    Write-Host "▶ Tests" -ForegroundColor Cyan
    & "$PSScriptRoot/test.ps1" -PortableOnly:$PortableOnly

    Write-Host "✓ Windows QA loop green" -ForegroundColor Green
}
finally {
    Pop-Location
}
