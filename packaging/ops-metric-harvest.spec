# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files

root = Path(SPECPATH).parent
# PyInstaller's PySide6.QtWidgets/QtGui hooks collect the Qt platform and image
# plugins. Collect only our assets rather than every unused Qt module.
a = Analysis(
    [str(root / 'ops_metric_harvest' / 'cli.py')],
    pathex=[str(root)],
    binaries=[],
    datas=collect_data_files('ops_metric_harvest.gui') + collect_data_files('tzdata'),
    hiddenimports=['ops_metric_harvest.gui.app', 'PySide6.QtWidgets', 'yaml'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['PyQt5', 'PyQt6', 'PySide2'],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [],
    name='ops-metric-harvest',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,  # Preserve CLI stdout/stderr and automation on Windows.
)
