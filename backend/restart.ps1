# MyCrew backend restart helper (Windows PowerShell)
#
# Workflow:
#   1. Run this once instead of `uvicorn ... --reload` — no auto-reload,
#      so edits during a long PM workflow won't kill the process.
#   2. Code changes accumulate on disk while the process is running.
#   3. When you want them live (or after PM finishes / fails), run
#      this script again. It kills the old listener + starts a fresh
#      one — the new process picks up every accumulated edit at once.
#
# Why not `--reload`: uvicorn watches api/services/domain/ports/infra/
# bootstrap and any save in those dirs kills mid-flight PM workflows.
# planner_cache_svc persists to disk so the next boot's UI can offer
# 「从断点重来」, but you still lose 5-10 min of LLM work per crash.

param(
    [int]$Port = 18321
)

$ErrorActionPreference = "Continue"

# Self-locate: cd to the directory holding this script (= backend/) so
# the uvicorn invocation below resolves the bootstrap.app module path
# regardless of where the user called the script from.
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir
Write-Host "[restart] cwd = $ScriptDir" -ForegroundColor DarkGray

Write-Host "[restart] killing any python on :$Port..." -ForegroundColor Cyan
# Note: $pid is a PowerShell built-in (current process ID) and is
# read-only; never use it as a loop var or it explodes with
# "VariableNotWritable" — we use $procPid here for the kill loop.
$lines = netstat -ano | Select-String ":$Port\s.*LISTENING"
$procPids = @{}
foreach ($line in $lines) {
    $parts = ($line.ToString() -split "\s+") | Where-Object { $_ -ne "" }
    if ($parts.Length -ge 5) {
        $procPids[[int]$parts[-1]] = $true
    }
}
foreach ($procPid in $procPids.Keys) {
    Write-Host "  → kill pid $procPid"
    try { Stop-Process -Id $procPid -Force -ErrorAction Stop } catch { Write-Host "    (already gone)" }
}
if ($procPids.Count -gt 0) { Start-Sleep -Milliseconds 400 }

Write-Host "[restart] launching fresh uvicorn on :$Port..." -ForegroundColor Cyan
# No --reload. Manual restart only. Set $env:MYCREW_DEV_RELOAD = "1"
# before running this if you genuinely want hot reload (PM crashes
# accepted).
$reloadFlag = if ($env:MYCREW_DEV_RELOAD -eq "1") { "--reload" } else { "" }

# CRITICAL: pin to backend/.venv/Scripts/uvicorn.exe, not whatever `uvicorn`
# is first on PATH. 2026-05-19 incident — bare `uvicorn` resolved to
# system Python 3.13's uvicorn, where litellm wasn't installed; CrewAI
# fell into LITELLM_AVAILABLE=False and PM Phase 2 died with "LiteLLM
# fallback package is not installed". The venv DOES have litellm.
$VenvUvicorn = Join-Path $ScriptDir ".venv\Scripts\uvicorn.exe"
if (-not (Test-Path $VenvUvicorn)) {
    Write-Host "[restart] FATAL: $VenvUvicorn not found. Run 'python -m venv .venv && .venv\Scripts\pip install -e .' first." -ForegroundColor Red
    exit 1
}
Write-Host "[restart] using $VenvUvicorn" -ForegroundColor DarkGray
& $VenvUvicorn bootstrap.app:create_app --factory --host 127.0.0.1 --port $Port $reloadFlag
