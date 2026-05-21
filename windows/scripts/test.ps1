#requires -Version 7.0
<#
.SYNOPSIS
    Run every WaiComputer test project. Generates an HTML coverage report
    under coverage/ on success.

    By default runs:
      - ../desktop/WaiComputer.Core.Tests (portable, works on Linux/macOS too)
      - WaiComputer.Native.Tests       (Windows-only)
      - WaiComputer.UITests            (Windows-only, requires built app)

    Pass -PortableOnly to skip Windows-only suites — useful from macOS or CI
    runners without WinUI tooling.
#>
param(
    [switch]$PortableOnly,
    [switch]$NoCoverage,
    [string]$Configuration = "Debug"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Push-Location $root
try {
    $projects = @("../desktop/WaiComputer.Core.Tests/WaiComputer.Core.Tests.csproj")
    if (-not $PortableOnly) {
        $projects += "WaiComputer.Native.Tests/WaiComputer.Native.Tests.csproj"
        $projects += "WaiComputer.UITests/WaiComputer.UITests.csproj"
    }

    foreach ($project in $projects) {
        $args = @("test", $project, "-c", $Configuration)
        if (-not $NoCoverage) {
            $args += @("--collect:XPlat Code Coverage")
        }
        Write-Host "▶ dotnet $($args -join ' ')" -ForegroundColor Cyan
        dotnet @args
    }

    if (-not $NoCoverage -and -not $PortableOnly) {
        $tool = (dotnet tool list -g | Select-String "dotnet-reportgenerator-globaltool")
        if (-not $tool) {
            dotnet tool install -g dotnet-reportgenerator-globaltool
        }
        reportgenerator -reports:"**\coverage.cobertura.xml" -targetdir:coverage -reporttypes:Html
        Write-Host "Coverage report: coverage/index.html" -ForegroundColor Green
    }
}
finally {
    Pop-Location
}
