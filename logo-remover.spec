# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for LogoRemover desktop app.

- Windowed (no console)
- One-dir build (COLLECT), app name LogoRemover
- macOS: target_arch='universal2' (Intel + Apple Silicon)
- Entry point: app.py (which imports remove_logos.py engine)

Build locally:
    pip install -r requirements.txt pyinstaller
    pyinstaller logo-remover.spec
"""

block_cipher = None

a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='LogoRemover',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,  # windowed: no console window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch='universal2',  # macOS universal2; ignored on Windows
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='LogoRemover',
)

# macOS .app bundle (only used on macOS builds; harmless on Windows)
app = BUNDLE(
    coll,
    name='LogoRemover.app',
    icon=None,
    bundle_identifier='com.logoremover.app',
)
