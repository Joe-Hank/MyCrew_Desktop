#!/usr/bin/env bash
# MyCrew backend restart helper (Git Bash / WSL)
#
# Same workflow as restart.ps1: no --reload by default, manual restart
# picks up accumulated code edits in one go.
#
# Usage:   bash backend/restart.sh                  # port 18321
#          bash backend/restart.sh 18322            # custom port
#          MYCREW_DEV_RELOAD=1 bash restart.sh      # opt back into --reload

set -u
PORT="${1:-18321}"

echo "[restart] killing any python on :$PORT..."
# Find PIDs holding that port (Windows path) — netstat works in Git Bash too.
PIDS=$(netstat -ano 2>/dev/null \
       | awk -v p=":$PORT" '$0 ~ p && /LISTENING/ {print $NF}' \
       | sort -u)
for pid in $PIDS; do
  echo "  → kill pid $pid"
  # taskkill on Windows; fall back to kill on POSIX.
  taskkill //PID "$pid" //F 2>/dev/null || kill -9 "$pid" 2>/dev/null || true
done
if [ -n "$PIDS" ]; then sleep 0.4; fi

echo "[restart] launching fresh uvicorn on :$PORT..."
RELOAD=""
if [ "${MYCREW_DEV_RELOAD:-0}" = "1" ]; then
  RELOAD="--reload"
fi
exec uvicorn bootstrap.app:create_app --factory --host 127.0.0.1 --port "$PORT" $RELOAD
