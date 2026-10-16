# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

a = Analysis(
    ['../ops_metric_harvest/cli.py'],
    pathex=['..'],
    binaries=[],
    datas=[],
    hiddenimports=[
        'ops_metric_harvest',
        'ops_metric_harvest.client',
        'ops_metric_harvest.engine',
        'ops_metric_harvest.models',
        'ops_metric_harvest.profiles',
        'ops_metric_harvest.starter_metrics',
        'ops_metric_harvest.version',
        'ops_metric_harvest.exporters',
        'ops_metric_harvest.exporters.base',
        'ops_metric_harvest.exporters.csv_export',
        'ops_metric_harvest.exporters.json_export',
        'ops_metric_harvest.exporters.xlsx_export',
        'ops_metric_harvest.exporters.table_export',
        'ops_metric_harvest.gui',
        'ops_metric_harvest.gui.server',
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
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='ops-metric-harvest',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
