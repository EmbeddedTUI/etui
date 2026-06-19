# -*- mode: python ; coding: utf-8 -*-
import sys
import os
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

# Collect textual CSS/assets and pygments style files
datas = []
datas += collect_data_files('textual')
datas += collect_data_files('pygments')

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
