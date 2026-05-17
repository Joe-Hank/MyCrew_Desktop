#!/usr/bin/env bash
# One-shot mirror: push the locally-staged Unity templates to a Gitee repo.
#
# Pre-conditions:
#   1. You already ran `python backend/scripts/stage_templates.py`
#      → templates staged at $STAGE_DIR (default: %LOCALAPPDATA%/Temp/mycrew-templates-stage).
#   2. You've created an empty PUBLIC repo on gitee.com, e.g.
#      https://gitee.com/Joe-Hank/Templates
#   3. You can `git push` to that repo from this machine (Gitee web login
#      OR SSH key + Gitee SSH).
#
# Usage:
#   bash backend/scripts/mirror_to_gitee.sh
#   bash backend/scripts/mirror_to_gitee.sh https://gitee.com/me/MyMirror.git
#
# This walks into the stage dir, ensures git is initialized + has the
# 4 templates committed (idempotent), points origin at the Gitee URL,
# and force-pushes. Re-running it after edits is safe.
set -eu

STAGE_DIR="${STAGE_DIR:-$LOCALAPPDATA/Temp/mycrew-templates-stage}"
# Allow override from args; default to current Gitee URL.
GITEE_URL="${1:-https://gitee.com/Joe-Hank/Templates.git}"

if [ ! -d "$STAGE_DIR" ]; then
  echo "[mirror] stage dir $STAGE_DIR missing — run stage_templates.py first."
  exit 1
fi

cd "$STAGE_DIR"

# Init repo if not already
if [ ! -d .git ]; then
  echo "[mirror] git init -b main"
  git init -b main
fi

# Make sure we're on main
git checkout -B main

# Stage + commit if there are uncommitted changes
if ! git diff --quiet || ! git diff --cached --quiet || [ -z "$(git log -1 --oneline 2>/dev/null)" ]; then
  git add -A
  git commit -m "Sync: 4 Unity templates (Universal 2D/3D, AR Mobile, MR Core)" \
    --allow-empty
fi

# Point origin at Gitee
if git remote get-url origin >/dev/null 2>&1; then
  git remote set-url origin "$GITEE_URL"
else
  git remote add origin "$GITEE_URL"
fi

echo "[mirror] pushing to $GITEE_URL (force) ..."
git push -u origin main --force
echo "[mirror] done."
