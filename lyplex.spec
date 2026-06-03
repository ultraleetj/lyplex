# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for LyPlex GUI
# Run: pyinstaller lyplex.spec

block_cipher = None

a = Analysis(
    ['lyplex_gui.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[
        'lyplex_tool',
        'mido',
        'mido.backends',
        'mido.backends.rtmidi',
        'cairosvg',
        'lxml',
        'lxml.etree',
        'PIL',
        'PIL.Image',
        'PIL.ImageDraw',
        'PIL.ImageFont',
        'wx',
    ],
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
    name='LyPlex',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    target_arch=None,
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
    name='LyPlex',
)
