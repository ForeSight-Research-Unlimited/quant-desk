#!/usr/bin/env bash
# ============================================================
#  Quant Desk -- one-command backup of the whole monorepo.
#  Stages everything (honouring .gitignore -- secrets, .venv,
#  candles.db, Project1 stay local), commits, and pushes.
#
#  Usage:
#      ./backup.sh                 # auto timestamped message
#      ./backup.sh "your message"
# ============================================================

set -e
cd "$(dirname "$(readlink -f "$0")")"

MSG="${1:-backup $(date +%Y-%m-%d_%H:%M)}"

git add -A
if git diff --cached --quiet; then
    echo "[backup] Nothing to commit."
else
    git commit -m "$MSG"
fi

if git remote get-url origin >/dev/null 2>&1; then
    git push
    echo "[backup] Pushed to $(git remote get-url origin)"
else
    echo "[backup] No 'origin' remote set yet. Add it once:"
    echo "         git remote add origin git@github.com:<owner>/quant-desk.git"
    echo "         git push -u origin main"
fi
