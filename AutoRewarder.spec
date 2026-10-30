# -*- mode: python ; coding: utf-8 -*-
import sys
import os
from PyInstaller.utils.hooks import collect_data_files, copy_metadata

is_windows = sys.platform == 'win32'
app_icon = os.path.join('assets', 'icon.ico') if is_windows else os.path.join('assets', 'icon.png')

hidden_imports = [
    'selenium.webdriver.edge.webdriver',
    'pystray',
    'PIL',
    'PIL.Image',
]
if is_windows:
    hidden_imports.append('pystray._win32')
else:
    hidden_imports += ['PySide6', 'gi']

a = Analysis(
    ['AutoRewarder.py'],
    pathex=[],
    binaries=[],
    datas=[('gui', 'gui'), ('assets', 'assets')]
        + collect_data_files('nlpaug')
        + copy_metadata('gdown')
        + copy_metadata('nlpaug'),
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

a.datas = [x for x in a.datas if not (x[0].startswith('assets/screenshots') or x[0].startswith('assets\\screenshots'))]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='AutoRewarder',
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
    icon=[app_icon],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='AutoRewarder',
)
