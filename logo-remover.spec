# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for the LogoRemover desktop app.

- Windowed (no console), one-dir build, app name LogoRemover
- macOS: builds for the architecture of the machine running it
  (Apple Silicon on macos-latest, Intel on macos-15-intel)
- Entry point: app.py (imports the remove_logos.py engine)

Build locally:
    pip install -r requirements.txt pyinstaller
    pyinstaller --noconfirm logo-remover.spec
"""
from PyInstaller.utils.hooks import collect_submodules

# send2trash picks its platform backend (Windows / macOS / Linux) at import
# time; collect all backends so the frozen app can always move files to Trash.
hiddenimports = collect_submodules('send2trash')

a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='LogoRemover',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,          # UPX-packed exes trigger more antivirus false positives
    console=False,      # windowed: no console window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,   # native arch of the build machine
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name='LogoRemover',
)

# macOS .app bundle (only used on macOS builds; ignored on Windows/Linux)
app = BUNDLE(
    coll,
    name='LogoRemover.app',
    icon=None,
    bundle_identifier='com.logoremover.app',
    info_plist={
        'CFBundleName': 'LogoRemover',
        'CFBundleDisplayName': 'LogoRemover',
        'NSHighResolutionCapable': True,
    },
)
