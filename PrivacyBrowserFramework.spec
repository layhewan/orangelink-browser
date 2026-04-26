# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_data_files
from PyInstaller.utils.hooks import collect_submodules

datas = [('D:\\XunLeiDownload\\browser\\.env.local', '.'), ('D:\\XunLeiDownload\\browser\\.env.example', '.')]
hiddenimports = ['playwright.sync_api', 'PySide6.QtCore', 'PySide6.QtGui', 'PySide6.QtWidgets']
datas += collect_data_files('playwright_stealth')
hiddenimports += collect_submodules('app')
hiddenimports += collect_submodules('playwright_stealth')


a = Analysis(
    ['D:\\XunLeiDownload\\browser\\scripts\\desktop_gui.py'],
    pathex=['D:\\XunLeiDownload\\browser'],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='PrivacyBrowserFramework',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='PrivacyBrowserFramework',
)
