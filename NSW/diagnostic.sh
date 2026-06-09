#!/usr/bin/env bash
# Mirror of diagnostic.bat. Sanity-check that the shell works
# and the script is being launched from where you think it is.

echo "Hello from diagnostic.sh -- if you see this, your shell works."
echo "Current directory: $(pwd)"
echo
echo "Quick sanity checks:"
echo "  bash version : $BASH_VERSION"
if command -v python3 >/dev/null 2>&1; then
    echo "  python3      : $(python3 --version 2>&1) at $(command -v python3)"
else
    echo "  python3      : NOT FOUND on PATH"
fi
if [ -x "../.venv/bin/python" ]; then
    echo "  shared venv  : present at ../.venv ($(../.venv/bin/python --version 2>&1))"
else
    echo "  shared venv  : not found at ../.venv (run start_nsw.sh first)"
fi
echo
echo "Press Enter to close."
read -r _
