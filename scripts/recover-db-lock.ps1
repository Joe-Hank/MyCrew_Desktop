# One-shot recovery for "database is locked" startup hang (2026-05-16 14:20 incident).
#
# What it does:
#   1. Lists all running python.exe processes
#   2. Asks user to confirm killing them (they're either the stuck
#      uvicorn or test scripts that didn't release the DB)
#   3. After kill, runs PRAGMA wal_checkpoint(TRUNCATE) to reset WAL
#   4. Reports final WAL size

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$Db = Join-Path $Root "data\db\mycrew.db"

if (-not (Test-Path $Db)) {
    Write-Error "Database not found at $Db"
    exit 1
}

Write-Host "`n== Running python.exe processes ==" -ForegroundColor Cyan
$pythons = Get-Process python -ErrorAction SilentlyContinue
if (-not $pythons) {
    Write-Host "(none)" -ForegroundColor Gray
} else {
    $pythons | Format-Table Id, ProcessName, WS, StartTime -AutoSize
    $confirm = Read-Host "`nKill all the python.exe processes above? (y/N)"
    if ($confirm -ne "y") {
        Write-Host "Aborted." -ForegroundColor Yellow
        exit 0
    }
    foreach ($p in $pythons) {
        try {
            Stop-Process -Id $p.Id -Force
            Write-Host "Killed PID $($p.Id)" -ForegroundColor Green
        } catch {
            Write-Host "Could not kill PID $($p.Id): $_" -ForegroundColor Red
        }
    }
    Start-Sleep -Seconds 1
}

Write-Host "`n== WAL state before checkpoint ==" -ForegroundColor Cyan
$wal = "$Db-wal"
$shm = "$Db-shm"
if (Test-Path $wal) {
    Write-Host "WAL size: $((Get-Item $wal).Length) bytes"
}

Write-Host "`n== Running PRAGMA wal_checkpoint(TRUNCATE) ==" -ForegroundColor Cyan
& python -c @"
import sqlite3
import pathlib
p = pathlib.Path(r'$Db')
conn = sqlite3.connect(str(p), timeout=5)
cur = conn.execute('PRAGMA wal_checkpoint(TRUNCATE)')
busy, log, checkpointed = cur.fetchall()[0]
conn.commit()
conn.close()
print(f'busy={busy}, log_pages={log}, checkpointed={checkpointed}')
"@

Write-Host "`n== WAL state after checkpoint ==" -ForegroundColor Cyan
if (Test-Path $wal) {
    Write-Host "WAL size: $((Get-Item $wal).Length) bytes"
} else {
    Write-Host "WAL file gone (truncated)" -ForegroundColor Green
}

Write-Host "`nDone. You can now restart the backend." -ForegroundColor Green
