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

Write-Host "[restart] killing any python on :$Port..." -ForegroundColor Cyan
$lines = netstat -ano | Select-String ":$Port\s.*LISTENING"
$pids = @{}
foreach ($line in $lines) {
    $parts = ($line.ToString() -split "\s+") | Where-Object { $_ -ne "" }
    if ($parts.Length -ge 5) {
        $pids[[int]$parts[-1]] = $true
    }
}
foreach ($pid in $pids.Keys) {
    Write-Host "  → kill pid $pid"
    try { Stop-Process -Id $pid -Force -ErrorAction Stop } catch { Write-Host "    (already gone)" }
}
if ($pids.Count -gt 0) { Start-Sleep -Milliseconds 400 }

Write-Host "[restart] launching fresh uvicorn on :$Port..." -ForegroundColor Cyan
# No --reload. Manual restart only. Set $env:MYCREW_DEV_RELOAD = "1"
# before running this if you genuinely want hot reload (PM crashes
# accepted).
$reloadFlag = if ($env:MYCREW_DEV_RELOAD -eq "1") { "--reload" } else { "" }
uvicorn bootstrap.app:create_app --factory --host 127.0.0.1 --port $Port $reloadFlag
