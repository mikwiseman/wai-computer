#requires -Version 7.0
<#
.SYNOPSIS
    Build all WaiComputer Windows projects in Release.
#>
param(
    [string]$Configuration = "Release"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

Push-Location $root
try {
    dotnet restore WaiComputer.sln
    dotnet build WaiComputer.sln -c $Configuration --no-restore
}
finally {
    Pop-Location
}
