# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec за AeroForge.

Сглобяване:  build_exe.bat   (или pyinstaller AeroForge.spec --noconfirm)
Резултат:    dist\\AeroForge\\AeroForge.exe
"""

block_cipher = None

a = Analysis(
    ['app/server.py'],
    pathex=['app'],
    binaries=[],
    datas=[('app/web', 'web')],
    hiddenimports=[
        'core.materials', 'core.airfoils', 'core.presets', 'core.aero',
        'core.propulsion', 'core.structure', 'core.cg', 'core.printcost',
        'core.weight', 'core.design', 'core.report',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'matplotlib', 'pandas', 'scipy', 'numpy'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='AeroForge',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
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
    upx=False,
    upx_exclude=[],
    name='AeroForge',
)
