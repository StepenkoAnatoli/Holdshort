# PowerShell entry point for the same onboarding proofs used on Linux/macOS.
# Requires Git for Windows (including Git Bash) and Python on PATH.
# Usage: .\tools\setup_machine.ps1 [-RepoUrl <url> [-Dest <dir>]]
param(
    [string]$RepoUrl = "",
    [string]$Dest = ""
)
$ErrorActionPreference = "Stop"
if ($Dest -and -not $RepoUrl) {
    throw "setup_machine: -Dest requires -RepoUrl"
}
$gitCommand = Get-Command git -CommandType Application -ErrorAction Stop | Select-Object -First 1
$gitRoot = Split-Path (Split-Path $gitCommand.Source -Parent) -Parent
$bashPath = Join-Path $gitRoot 'bin/bash.exe'
if (-not (Test-Path -LiteralPath $bashPath -PathType Leaf)) {
    $bashCommand = Get-Command bash -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $bashCommand) {
        throw "setup_machine: install Git Bash and put bash on PATH"
    }
    $bashPath = $bashCommand.Source
}
# install_hooks.py also needs to find Bash when invoked by the setup script.
$env:PATH = (Split-Path $bashPath -Parent) + ';' + $env:PATH
$scriptPath = (Join-Path $PSScriptRoot 'setup_machine.sh').Replace('\', '/')
$setupArguments = @()
if ($RepoUrl) {
    $setupArguments += $RepoUrl
    if ($Dest) { $setupArguments += $Dest }
}
& $bashPath $scriptPath @setupArguments
exit $LASTEXITCODE
