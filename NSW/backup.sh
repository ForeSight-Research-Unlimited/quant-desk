#!/usr/bin/env bash
# ============================================================
#  NSW one-click backup-to-GitHub (Linux / macOS).
#  ----------------------------------------------------------
#  Mirror of backup.bat. Stages all changes, commits with a
#  message you type (or a timestamped default), and pushes to
#  origin/main.
#
#  Safe to run with no changes -- it detects that and exits
#  without making an empty commit.
# ============================================================

set -e
cd "$(dirname "$(readlink -f "$0")")"

echo
echo "============================================================"
echo " NSW backup-to-GitHub"
echo "============================================================"
echo

# ----- 1. Confirm this is a git repo with a remote -----------
if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    echo "[error] This folder is not a git repository."
    echo "        Run: git init -b main"
    exit 1
fi
if ! git remote get-url origin >/dev/null 2>&1; then
    echo "[error] No origin remote is configured."
    echo "        Run: git remote add origin https://github.com/<org>/<repo>.git"
    exit 1
fi

# ----- 2. Show what's about to be staged ---------------------
echo "Current working-tree status:"
echo "------------------------------------------------------------"
git -c color.status=always status --short
echo "------------------------------------------------------------"
echo

# ----- 3. Bail (kinda) if there's nothing to commit ----------
if [ -z "$(git status --porcelain)" ]; then
    echo "[ok] Nothing to commit. Working tree is clean."
    echo
    echo "Pushing any unpushed local commits anyway..."
    git push
    echo
    exit 0
fi

# ----- 4. Ask for a commit message (default: timestamped) ----
STAMP=$(date "+%Y-%m-%d %H:%M")
DEFAULT_MSG="backup $STAMP"

echo "Type a commit message and press Enter, or just press Enter"
echo "to use the default (shown in brackets):"
read -r -p "  [$DEFAULT_MSG]: " MSG
if [ -z "$MSG" ]; then
    MSG="$DEFAULT_MSG"
fi

# ----- 5. Stage everything -----------------------------------
echo
echo "[step] git add -A"
git add -A

# ----- 6. Commit ---------------------------------------------
echo "[step] git commit -m \"$MSG\""
git commit -m "$MSG"

# ----- 7. Push -----------------------------------------------
echo "[step] git push"
if ! git push; then
    echo "[error] git push failed. See message above."
    echo "        Common fixes:"
    echo "          - First-time push on a new branch:  git push -u origin main"
    echo "          - Auth: configure a credential helper (e.g. gh auth login)"
    echo "            or use a Personal Access Token:"
    echo "            https://github.com/settings/tokens?type=beta"
    exit 1
fi

echo
echo "============================================================"
echo " Backup pushed."
echo " Remote: $(git remote get-url origin)"
echo "============================================================"
