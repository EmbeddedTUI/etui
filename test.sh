#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

echo "=== Built-in self-tests ==="
pdm run etui --self-test

echo ""
echo "=== pytest ==="
pdm run pytest -p no:xonsh tests/ etui/self_test.py "$@"
