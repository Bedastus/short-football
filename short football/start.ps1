# Run from PowerShell as:  .\start.ps1
#
# Same job as start.bat. It exists because the per-round command is long, and a
# long command pasted into PowerShell is where the quoting goes wrong - note
# that PowerShell has no backslash line continuation, so a wrapped bash-style
# command parses "--" as a unary operator and fails before Python is reached.

$Bankroll = 21000
$Base     = 200
$Stages   = 5
$StopLoss = 19800

Set-Location -LiteralPath $PSScriptRoot

# The py launcher is the reliable way to reach Python on Windows; plain
# "python" can open the Microsoft Store instead of running anything.
$Py = if (Get-Command py -ErrorAction SilentlyContinue) { @('py', '-3') }
      elseif (Get-Command python -ErrorAction SilentlyContinue) { @('python') }
      else { $null }

if (-not $Py) {
    Write-Host ""
    Write-Host "Python was not found. Install it from https://www.python.org/downloads/"
    Write-Host 'and tick "Add python.exe to PATH" during setup.'
    Read-Host "Press Enter to close"
    exit 1
}

$exe, $pre = $Py[0], @($Py[1..($Py.Count - 1)])

if (-not (Test-Path 'data\sokaligi_state.json')) {
    Write-Host 'Setting up a new ladder...'
    & $exe @pre sokaligi_bot.py init `
        --bankroll $Bankroll --base $Base --stages $Stages --step 100 `
        --books soka-1 soka-2 soka-3 --feed shared --stop-loss $StopLoss
    if ($LASTEXITCODE -ne 0) { Read-Host "Press Enter to close"; exit 1 }
    Write-Host ""
}

& $exe @pre sokaligi_bot.py run
if ($LASTEXITCODE -ne 0) { Read-Host "Press Enter to close"; exit 1 }
