# -*- mode: python ; coding: utf-8 -*-
import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

block_cipher = None

v2_root = Path(r'D:\llama-console\src\llama_console_v2')
v2_parent = Path(r'D:\llama-console\src')

# All submodules to ensure PyInstaller treats the package as one
hidden = []
for pkg_name in ['llama_console_v2',
                 'llama_console_v2.backend',
                 'llama_console_v2.pages',
                 'llama_console_v2.widgets',
                 'PySide6',
                 'PySide6.QtCore',
                 'PySide6.QtGui',
                 'PySide6.QtWidgets',
                 'psutil',
                 'httpx']:
    hidden += collect_submodules(pkg_name)
# explicit safety nets
hidden += ['app', 'theme', 'main_window', 'backend',
           'pages.console', 'pages.settings',
           'widgets.card', 'widgets.buttons', 'widgets.chip_icon',
           'widgets.key_value', 'widgets.page_chrome', 'widgets.progress_bar',
           'widgets.server_control', 'widgets.stat_block', 'widgets.status_pill',
           'widgets.elide_label']

a = Analysis(
    [str(v2_root / '__main__.py')],
    pathex=[str(v2_parent)],
    binaries=[],
    datas=[],
    hiddenimports=hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'PySide6.Qt3D', 'PySide6.QtCharts', 'PySide6.QtDataVisualization',
        'PySide6.QtMultimedia', 'PySide6.QtMultimediaWidgets', 'PySide6.QtNetwork',
        'PySide6.QtNetworkAuth', 'PySide6.QtOpenGL', 'PySide6.QtPositioning',
        'PySide6.QtQml', 'PySide6.QtQuick', 'PySide6.QtQuick3D',
        'PySide6.QtQuickWidgets', 'PySide6.QtRemoteObjects', 'PySide6.QtScxml',
        'PySide6.QtSensors', 'PySide6.QtSerialPort', 'PySide6.QtSql',
        'PySide6.QtTest', 'PySide6.QtWebChannel', 'PySide6.QtWebEngine',
        'PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets', 'PySide6.QtWebSockets',
        'PySide6.QtXml',
        'tkinter', 'unittest', 'email', 'html', 'http', 'xml', 'xmlrpc',
        'pydoc', 'doctest',
    ],
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
    name='nlama',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(Path(r'D:\llama-console\assets\nlama.ico')),
)

