# setup_machine.ps1 - Windows/PowerShell onboarding for Holdshort.
#
# Mirrors the common path of tools/setup_machine.sh using PowerShell-native
# commands. The full proof sequence (scratch commit / fake-key refusal) is
# easier to run under Git Bash; this script covers clone, hook wiring, gate
# baseline, secrets scan, and the A2 dry-run warm-up.
#
# Usage:
#   .\tools\setup_machine.ps1                      # current checkout
#   .\tools\setup_machine.ps1 -RepoUrl <url> -Dest <dir>

param(
    [string]$RepoUrl = "",
    [string]$Dest = ""
)

$ErrorActionPreference = "Stop"

function Fail($msg) { Write-Error "setup_machine: FAIL - $msg"; exit 1 }

if ($RepoUrl) {
    if (-not $Dest) { $Dest = [System.IO.Path]::GetFileNameWithoutExtension($RepoUrl) }
    Write-Host "==> cloning into $Dest"
    git clone $RepoUrl $Dest
    Set-Location $Dest
} else {
    $top = git rev-parse --show-toplevel 2>$null
    if (-not $top) { Fail "not inside a git repo (pass -RepoUrl to clone)" }
    Set-Location $top
}

# clean worktree check
$status = git status --porcelain
if ($status) { Fail "worktree has uncommitted changes; commit or stash first" }

Write-Host "==> wiring core.hooksPath"
python tools/install_hooks.py
if ($LASTEXITCODE -ne 0) { Fail "install_hooks" }

# PROOF 1: pre-commit hook fires on a clean scratch commit
Write-Host "==> PROOF 1: pre-commit hook fires on a clean scratch commit"
git config user.name "setup-gate-proof"
git config user.email "setup-gate-proof@example.invalid"
$scratch = "setup_gate_proof_$PID"
Set-Content -Path "$scratch.txt" -Value "# gate proof (rolled back)"
git add "$scratch.txt"
git commit -m "setup: gate proof (rolled back, not pushed)" *> $null
if ($LASTEXITCODE -eq 0) {
    git reset -q --hard HEAD~1 *> $null
    Remove-Item "$scratch.txt" -ErrorAction SilentlyContinue
    Write-Host "    PASS - hook ran the gate and allowed a clean commit"
} else {
    git reset -q -- "$scratch.txt" *> $null
    Remove-Item "$scratch.txt" -ErrorAction SilentlyContinue
    Fail "hook did not allow a clean commit - gate wiring is broken"
}

# PROOF 2: a staged fake key is REFUSED (fail-closed)
Write-Host "==> PROOF 2: a staged fake key is REFUSED (fail-closed)"
$fakeVal = "sk-ant-fake-setup-proof-"
$fakeVal2 = "000000"
$fakeVal = $fakeVal + $fakeVal2
$slug = [System.IO.Path]::GetTempFileName()
Set-Content -Path $slug -Value "ANTHROPIC_API_KEY=$fakeVal"
Get-Content $slug | Add-Content -Path "README.md"
Remove-Item $slug
git add README.md
git commit -m "setup: leak proof (must be refused)" *> $null
if ($LASTEXITCODE -eq 0) {
    git reset -q --hard HEAD~1 *> $null
    Fail "hook ACCEPTED a fake key - enforcement is not working"
} else {
    git reset -q -- README.md *> $null
    git checkout -q -- README.md *> $null
    Write-Host "    PASS - refusal confirmed (commit blocked)"
}

Write-Host "==> gate baseline"
$gateOut = python tools/run_regression.py
if ($LASTEXITCODE -ne 0) { $gateOut; Fail "regression gate is red on a fresh clone" }
$gateOut | Select-Object -Last 1

Write-Host "==> PREFLIGHT A0: secrets scan"
python tools/check_secrets.py
if ($LASTEXITCODE -ne 0) { Fail "check_secrets not clean" }
Write-Host "    PASS - clean"

Write-Host "==> PREFLIGHT A2: dry-run warm-up (no network)"
$tmp = New-Item -ItemType Directory -Path ([System.IO.Path]::GetTempPath() + [Guid]::NewGuid())
$ledger = Join-Path $tmp "dryrun_ledger.jsonl"
$json = Join-Path $tmp "dry.json"
python tools/live_dispatcher.py --profile cloud-C --task-id dryrun-1 --request "probe" --work-bound 0.01 --review-bound 0.01 --expected-in-tokens 10000 --expected-out-tokens 1000 --ledger $ledger *> $json
if ($LASTEXITCODE -ne 0) { Get-Content $json; Fail "cloud-C dry-run must dispatch (exit 0)" }
if (-not (Select-String -Path $json -Pattern '"decision": "dispatched"' -Quiet)) { Get-Content $json; Fail "dry-run JSON missing dispatched" }
if (-not (Select-String -Path $ledger -Pattern '"decision": "dispatched"' -Quiet)) { Get-Content $ledger; Fail "ledger line not written" }
Write-Host "    PASS - cloud-C dispatched and ledger line written"

$gate4 = Join-Path $tmp "gate4.json"
python tools/live_dispatcher.py --profile cloud-XYZ --task-id dryrun-2 --request "x" --work-bound 0.01 --review-bound 0.01 --ledger $ledger *> $gate4
if ($LASTEXITCODE -ne 1) { Get-Content $gate4; Fail "cloud-XYZ must be Gate-4 refused (exit 1)" }
if (-not (Select-String -Path $gate4 -Pattern '"decision": "unknown-profile"' -Quiet)) { Get-Content $gate4; Fail "Gate-4 JSON missing unknown-profile" }
Write-Host "    PASS - unknown-profile Gate-4 fail-closed"

Remove-Item -Recurse -Force $tmp
Write-Host "setup_machine: DONE - gate enforced, preflight (A0-A2) verified."
exit 0
