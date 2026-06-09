#!/usr/bin/env bash
# ============================================================================
#  Quant Desk -- environment bootstrap (the ONE place that owns the venv).
#  ----------------------------------------------------------------------------
#  Creates the shared virtual environment at <workspace root>/.venv and installs
#  every module listed in modules.txt (editable) plus the shared research libs
#  (requirements-dev.txt). This is the ONLY script allowed to create or modify
#  the venv. Per-module launchers (NSW/start_nsw.sh, future TA/backtester/...)
#  assume the venv already exists and just run their thing.
#
#  Re-run this whenever you:
#    - add a new module        (add its folder to modules.txt first)
#    - change a module's deps   (edit its pyproject.toml)
#    - change requirements-dev.txt
#  Editing a module's *code* does NOT need a re-run -- modules are installed
#  editable, so code changes are picked up live.
#
#  Usage (from anywhere):
#      ./first_install/install.sh
#  or from inside first_install/:
#      ./install.sh
#
#  Linux/Ubuntu only. If you ever need Windows again, that's a separate refactor.
# ============================================================================

set -euo pipefail

# ----- Resolve paths --------------------------------------------------------
HERE="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"   # first_install/
ROOT="$(dirname "$HERE")"                                 # workspace root
VENV_DIR="$ROOT/.venv"
VENV_PY="$VENV_DIR/bin/python"
MANIFEST="$HERE/modules.txt"
DEV_REQS="$ROOT/requirements-dev.txt"

echo
echo "============================================================"
echo " Quant Desk -- environment bootstrap"
echo " workspace root: $ROOT"
echo "============================================================"
echo

# ----- 1. Find a Python interpreter -----------------------------------------
# Preference: python3.12 / python3.11 have prebuilt wheels for every pinned dep
# (notably fyers-apiv3's aiohttp). Fall back to whatever python3 is on PATH.
PY_CMD=""
for cand in python3.12 python3.11 python3; do
    if command -v "$cand" >/dev/null 2>&1; then PY_CMD="$cand"; break; fi
done
if [ -z "$PY_CMD" ]; then
    echo "[error] No python3 found on PATH. Install Python 3.12:"
    echo "          sudo apt update"
    echo "          sudo apt install python3.12 python3.12-venv python3-tk"
    exit 1
fi
echo "[ok] Python: $PY_CMD ($("$PY_CMD" --version 2>&1))"

# ----- 2. Create the shared venv (only if missing) --------------------------
if [ ! -x "$VENV_PY" ]; then
    echo "[setup] Creating shared venv at $VENV_DIR ..."
    "$PY_CMD" -m venv "$VENV_DIR"
fi
if [ ! -x "$VENV_PY" ]; then
    echo "[error] venv creation failed. On Ubuntu you usually need:"
    echo "          sudo apt install python3.12-venv"
    exit 1
fi
echo "[ok] Shared venv: $VENV_PY"

# ----- 3. Upgrade pip -------------------------------------------------------
echo "[setup] Upgrading pip ..."
"$VENV_PY" -m pip install --upgrade pip --disable-pip-version-check

# ----- 4. Editable-install every module in the manifest ---------------------
echo "[setup] Installing modules from $(basename "$MANIFEST") ..."
while IFS= read -r raw || [ -n "$raw" ]; do
    line="${raw%%#*}"                          # strip trailing comment
    line="$(echo "$line" | xargs || true)"     # trim whitespace
    [ -z "$line" ] && continue
    MOD_DIR="$ROOT/$line"
    if [ ! -f "$MOD_DIR/pyproject.toml" ]; then
        echo "[warn] skipping '$line' -- no pyproject.toml at $MOD_DIR"
        continue
    fi
    echo "[setup]   -> $line (editable)"
    "$VENV_PY" -m pip install -e "$MOD_DIR" --disable-pip-version-check
done < "$MANIFEST"

# ----- 5. Shared research libs ----------------------------------------------
if [ -f "$DEV_REQS" ]; then
    echo "[setup] Installing shared research libs (requirements-dev.txt) ..."
    "$VENV_PY" -m pip install -r "$DEV_REQS" --disable-pip-version-check
fi

# ----- 6. Reconcile the websocket-client pin --------------------------------
# fyers-apiv3 needs websocket-client==1.6.1 exactly; the jupyter stack tries to
# bump it to >=1.7. Force it back so Fyers auth/backfill can never break.
# (See KNOWN_BUGS.md #11.)
echo "[setup] Pinning websocket-client==1.6.1 (Fyers requirement) ..."
"$VENV_PY" -m pip install "websocket-client==1.6.1" --disable-pip-version-check

# ----- 7. Smoke check -------------------------------------------------------
echo "[check] Verifying the install ..."
"$VENV_PY" - <<'PY'
import nsw
from nsw.loader import load_data          # noqa: F401  (import is the test)
from nsw import fyers_client              # noqa: F401  (most at risk from the pin)
import matplotlib                         # research libs present
print(f"[ok] nsw {nsw.__version__} + research libs import cleanly")
PY

echo
echo "============================================================"
echo " Done. Shared environment is ready at .venv/"
echo " Next: run NSW with   cd NSW && ./start_nsw.sh"
echo "============================================================"
echo
