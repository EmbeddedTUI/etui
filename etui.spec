# -*- mode: python ; coding: utf-8 -*-
import sys
import os
from PyInstaller.utils.hooks import (
    collect_data_files,
    collect_submodules,
    copy_metadata,
)

block_cipher = None

# Collect textual CSS/assets and pygments style files
datas = []
datas += collect_data_files('textual')
datas += collect_data_files('pygments')
datas += [('etui/doc', 'etui/doc')]

# First-party tab plugins are discovered at runtime via the `etui.tabs`
# entry-point group, which PyInstaller's static analysis cannot follow. Collect
# each plugin's modules, its package data (guide.md, workflow yaml, CSS, ...) and
# — critically — its dist-info metadata, so importlib.metadata.entry_points()
# still finds them inside the frozen binary. Build with the plugins installed
# (`pdm install -G default-tabs` or `./dev-install.sh`).
_FIRST_PARTY_PLUGINS = [
    "etui-tools", "etui-venv", "etui-cmake", "etui-workflow",
    "etui-serial", "etui-github", "etui-git", "etui-probe", "etui-lldb",
    "etui-plugin-manager",
]

# Add README or other static files if they exist
if os.path.exists('README.md'):
    datas += [('README.md', '.')]

binaries = []

hiddenimports = []
hiddenimports += collect_submodules('textual')
hiddenimports += collect_submodules('pygments')
hiddenimports += collect_submodules('usb')
hiddenimports += collect_submodules('xonsh')
hiddenimports += [
    'usb.core',
    'usb.backend.libusb1',
]

# Bundle the first-party plugins (modules + data + entry-point metadata).
for _dist in _FIRST_PARTY_PLUGINS:
    _mod = _dist.replace("-", "_")
    try:
        hiddenimports += collect_submodules(_mod)
        datas += collect_data_files(_mod)
        datas += copy_metadata(_dist)
    except Exception as _exc:  # plugin not installed in this build env
        print(f"etui.spec: skipping plugin {_dist!r}: {_exc}")

a = Analysis(
    ['etui/main.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Exclude the phantom top-level `workflow` module that only exists via the
    # non-package fallback import in etui/tabs/workflow.py
    # (`from workflow.engine import ...`). The frozen app always uses the
    # `etui.workflow` package path, so it is dead weight here — and the bundled
    # PyInstaller contrib hook-workflow.py would otherwise try to read metadata
    # for a non-existent `workflow` distribution and abort the build.
    excludes=['workflow'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='etui',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
