#!/usr/bin/env bash
# ============================================================
#  NSW launcher -- starts the setup / data server. That's all.
#  ----------------------------------------------------------
#  This script does NOT create or modify the venv. The shared
#  Quant Desk venv is built once by first_install/install.sh.
#  Here we only: verify the venv exists, then launch the server.
#
#  Run with:  ./start_nsw.sh
#
#  config.json is handled by NSW itself (nsw.config.ensure_config_exists
#  creates it from config.example.json on startup if missing).
# ============================================================

set -e

# Anchor to the directory this script lives in (NSW/).
cd "$(dirname "$(readlink -f "$0")")"

VENV_PY="../.venv/bin/python"

# ----- Require the shared venv ------------------------------
if [ ! -x "$VENV_PY" ]; then
    echo "[error] Shared venv not found at ../.venv"
    echo
    echo "        The environment hasn't been bootstrapped yet."
    echo "        Build it once from the workspace root:"
    echo
    echo "          ./first_install/install.sh"
    echo
    exit 1
fi

# ----- Launch the server ------------------------------------
echo
echo "============================================================"
echo " Starting NSW setup server on https://127.0.0.1:5001/"
echo " Open the URL in your browser, accept the self-signed cert"
echo " warning (Advanced -> Proceed) the first time."
echo " Press Ctrl+C in this terminal to stop the server."
echo "============================================================"
echo

exec "$VENV_PY" -B -m nsw.server
