#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

echo "=== Built-in self-tests ==="
pdm run etui --self-test

echo ""
echo "=== pytest (core) ==="
pdm run pytest -p no:xonsh tests/ etui/self_test.py "$@"

echo ""
echo "=== pytest (first-party plugins) ==="
# Each plugin is its own distribution with a tests/test_tab.py. Run them one at
# a time with the plugin's OWN source dir first on the path, so:
#   * tests exercise the working-tree source (not a stale installed copy), and
#   * the duplicate test_tab.py basenames don't collide during collection.
# This catches plugin regressions (e.g. a tab's operation lifecycle) here.
for plugin_dir in plugins/*/; do
    [ -d "${plugin_dir}tests" ] || continue
    echo "--- ${plugin_dir} ---"
    PYTHONPATH="${plugin_dir}${PYTHONPATH:+:$PYTHONPATH}" \
        pdm run pytest -p no:xonsh "${plugin_dir}tests" --import-mode=importlib "$@"
done
