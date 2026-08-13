# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec — builds a fully standalone `Meta Nuke.app`.

The result has NO dependency on the system Python, pyenv, or the vault venv:
everything (Pillow, pillow-heif, PyMuPDF, tkinterdnd2 + its native tkdnd
library, numpy) is bundled inside the .app. This also fixes the drag-and-drop
crash that happens when the host Python's Tcl/Tk ships an incompatible tkdnd,
because PyInstaller collects the matching tkdnd binaries.

Build:   pyinstaller --noconfirm MetaNuke.spec
Output:  dist/Meta Nuke.app
"""

from PyInstaller.utils.hooks import collect_all

datas, binaries, hiddenimports = [], [], []

# Pull in packages that ship native libraries / data files.
for pkg in ('PIL', 'pillow_heif', 'fitz', 'tkinterdnd2', 'numpy'):
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception:
        pass  # optional package not installed in this build env


a = Analysis(
    ['meta_nuke.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=['pytest'],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='MetaNuke',
    debug=False,
    strip=False,
    upx=False,
    console=False,            # windowed GUI app, no terminal
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='assets/MetaNuke.icns',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name='MetaNuke',
)

app = BUNDLE(
    coll,
    name='Meta Nuke.app',
    icon='assets/MetaNuke.icns',
    bundle_identifier='com.metanuke.app',
    info_plist={
        'CFBundleName': 'Meta Nuke',
        'CFBundleDisplayName': 'Meta Nuke',
        'CFBundleShortVersionString': '1.5.0',
        'CFBundleVersion': '3',
        'NSHighResolutionCapable': True,
        'NSRequiresAquaSystemAppearance': False,
        'LSMinimumSystemVersion': '10.13',
        'NSHumanReadableCopyright': 'MIT License',
    },
)
