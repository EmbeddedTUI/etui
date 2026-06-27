#!/usr/bin/env bash
# Configure PDM in the current directory to use the shared etui venv,
# then install the project's dependencies into it.
# Usage: run from any plugin directory (etui_system, etui_yocto, etc.)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_PYTHON="$SCRIPT_DIR/venv/bin/python3"

if [[ ! -x "$VENV_PYTHON" ]]; then
    echo "ERROR: venv not found at $VENV_PYTHON" >&2
    echo "Run 'pdm install' inside $SCRIPT_DIR first." >&2
    exit 1
fi

pdm use "$VENV_PYTHON"

# PDM's resolver can't find etui (not on PyPI). Install via pip instead:
# register the plugin entry point and pull in all deps except etui,
# which is already present in the shared venv.
"$VENV_PYTHON" -m pip install -e . --no-deps -q
"$VENV_PYTHON" -m pip install \
    $("$VENV_PYTHON" -c "
import tomllib, pathlib
data = tomllib.loads(pathlib.Path('pyproject.toml').read_text())
deps = [d for d in data['project'].get('dependencies', []) if not d.startswith('etui')]
print(' '.join(deps))
") -q
echo "Done. Plugin installed into shared etui venv."
