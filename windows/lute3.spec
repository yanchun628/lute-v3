# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for the Lute3 Windows desktop build.
# Build with:  windows\build.ps1   (or: pyinstaller windows\lute3.spec)
#
# Produces a one-folder build in dist\Lute3\ (one-folder starts much
# faster than one-file, and triggers fewer antivirus false positives).

import os
import MeCab
import ipadic
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

SPEC_DIR = os.path.abspath(SPECPATH)
ROOT = os.path.dirname(SPEC_DIR)
ICON = os.path.join(ROOT, "lute", "static", "favicon.ico")

# All Lute templates, static files, schema, language defs, demo data...
datas = collect_data_files("lute", excludes=["**/__pycache__", "config/config.yml"])

# Japanese: MeCab dll (from mecab-python3 wheel) + ipadic dictionary.
mecab_dll = os.path.join(os.path.dirname(MeCab.__file__), "libmecab.dll")
binaries = [(mecab_dll, "MeCab")]
datas += [(ipadic.DICDIR, os.path.join("ipadic", "dicdir"))]

hiddenimports = collect_submodules("lute") + [
    "_cffi_backend",
    "pystray._win32",
]

excludes = [
    "MeCab",  # only the dll is needed; natto-py does the binding.
    "tkinter",
    "pytest",
    "pytest_bdd",
    "playwright",
    "pylint",
    "black",
    "coverage",
    "invoke",
]

a = Analysis(
    [os.path.join(SPEC_DIR, "lute3_entry.py")],
    pathex=[ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=excludes,
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Lute3",
    icon=ICON,
    console=False,
    upx=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    name="Lute3",
    upx=False,
)
