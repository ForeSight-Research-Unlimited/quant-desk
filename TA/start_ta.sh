#!/usr/bin/env bash
# ============================================================
#  TA launcher -- starts the chart server. That's all.
#  ----------------------------------------------------------
#  Like start_nsw.sh: it does NOT create the venv (that's
#  first_install/install.sh). It verifies the shared venv
#  exists, then launches the TA chart server.
#
#  Run with:  ./start_ta.sh
#  Then open: http://127.0.0.1:5002/
# ============================================================

set -e
cd "$(dirname "$(readlink -f "$0")")"

VENV_PY="../.venv/bin/python"

if [ ! -x "$VENV_PY" ]; then
    echo "[error] Shared venv not found at ../.venv"
    echo
    echo "        Bootstrap the environment first (from the workspace root):"
    echo "          ./first_install/install.sh"
    echo
    exit 1
fi

echo
echo "============================================================"
echo " Starting TA chart server on http://127.0.0.1:5002/"
echo " Open the URL in your browser."
echo " Press Ctrl+C in this terminal to stop the server."
echo "============================================================"
echo

exec "$VENV_PY" -B -m ta.server
