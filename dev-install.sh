#!/usr/bin/env bash
# Make the first-party plugins under plugins/* import from SOURCE in the pdm
# .venv, so edits take effect without reinstalling.
#
# Background: PDM 2.x has no native workspace and cannot express the plugins as
# editable members (it dedupes an editable local vs the non-editable `default-tabs`
# extra). So we do a lightweight editable overlay instead of `pip install -e`
# (the pdm .venv has no pip): keep each plugin's installed dist-info (entry points
# + metadata), but replace the COPIED package dir with a `.pth` that points at the
# working-tree source.
#
# Usage:
#   pdm install --group default-tabs   # gets deps + dist-info (+ copied packages)
#   ./dev-install.sh                   # overlay source for live editing
#
# A later `pdm install` re-copies the packages (shadowing source) — just rerun
# this script. To undo, run `pdm install --group default-tabs` again.
set -euo pipefail
cd "$(dirname "$0")"

site="$(pdm run python -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')"
echo "site-packages: $site"

shopt -s nullglob
count=0
for plugin_dir in plugins/*/; do
    [ -f "${plugin_dir}pyproject.toml" ] || continue
    # the import package is the single etui_* dir inside the plugin
    pkg_path="$(find "$plugin_dir" -maxdepth 1 -type d -name 'etui_*' | head -n1)"
    [ -n "$pkg_path" ] || continue
    pkg_name="$(basename "$pkg_path")"
    abs_parent="$(cd "$plugin_dir" && pwd)"

    if [ ! -d "${site}/${pkg_name}" ] && [ ! -f "${site}/__editable_${pkg_name}.pth" ]; then
        echo "  ! ${pkg_name} not installed — run 'pdm install --group default-tabs' first" >&2
    fi

    # 1. drop the copied package dir so it can't shadow the source on sys.path
    rm -rf "${site:?}/${pkg_name}"
    # 2. point imports at the source tree (a .pth line is added to sys.path)
    printf '%s\n' "$abs_parent" > "${site}/__editable_${pkg_name}.pth"
    echo "  ${pkg_name} -> ${abs_parent}"
    count=$((count + 1))
done

echo "Overlaid ${count} plugin(s) as editable. Plugins now import from source."
echo "Rerun this after any 'pdm install'."
