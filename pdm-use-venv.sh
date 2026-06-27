#!/usr/bin/env bash
# Configure PDM in the current directory to use the shared etui venv.
# Usage: run from any plugin directory (etui_system, etui_yocto, etc.)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_PYTHON="$SCRIPT_DIR/etui/venv/bin/python3"

if [[ ! -x "$VENV_PYTHON" ]]; then
    echo "ERROR: venv not found at $VENV_PYTHON" >&2
    echo "Run 'pdm install' inside $SCRIPT_DIR/etui first." >&2
    exit 1
fi

pdm use "$VENV_PYTHON"
echo "PDM will now use: $VENV_PYTHON"
