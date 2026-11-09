# start-all.ps1
# Starts DexTrader's 2 services in ONE Windows Terminal tab split into 2 panes
# (instead of start_dev.bat opening 2 separate windows).
#
# Usage (from a PowerShell prompt, or right-click -> "Run with PowerShell"):
#   .\start-all.ps1             # open one tab, split in 2, auto-start each service
#   .\start-all.ps1 -Manual     # open one tab, split in 2, just sit in the right folders
#                               #   so YOU type the commands yourself
#   .\start-all.ps1 -Install    # like default, but also run npm/pip install first
#
# Tip: run it from inside an existing Windows Terminal window and it will add the
# split tab to that window (the -w 0 flag targets the current window).

param(
    [switch]$Manual,
    [switch]$Install
)

$root    = Split-Path -Parent $MyInvocation.MyCommand.Path
$frontend = Join-Path $root 'frontend'
$backend = Join-Path $root 'backend'

if (-not (Get-Command wt -ErrorAction SilentlyContinue)) {
    Write-Error "Windows Terminal (wt) not found. Install it with: winget install Microsoft.WindowsTerminal"
    exit 1
}

# Backtick-escaped `;` separates the wt sub-commands; panes run PowerShell with -NoExit
# so each pane stays open after its command finishes/errors.
# npm.cmd (not npm) is used because npm.ps1 is blocked by the execution policy.

if ($Manual) {
    # Just open the tab split in 2, each pane already in the right folder.
    wt -w 0 new-tab -d "$frontend" `
    `; sp -d "$backend"
}
elseif ($Install) {
    # Auto-start, reinstalling deps first.
    wt -w 0 new-tab -d "$frontend" powershell -NoExit -ExecutionPolicy Bypass -Command "npm.cmd install; npm.cmd run dev" `
    `; sp -d "$backend" powershell -NoExit -ExecutionPolicy Bypass -Command "pip install -r requirements.txt; python -m uvicorn app.main:app --reload"
}
else {
    # Auto-start (assumes deps are already installed - fastest).
    wt -w 0 new-tab -d "$frontend" powershell -NoExit -ExecutionPolicy Bypass -Command "npm.cmd run dev" `
    `; sp -d "$backend" powershell -NoExit -ExecutionPolicy Bypass -Command "python -m uvicorn app.main:app --reload"
}
