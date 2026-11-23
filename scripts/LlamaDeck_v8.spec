# -*- mode: python ; coding: utf-8 -*-
# NOTE (2026-08-31 reorg): spec moved from repo root to scripts\.
# Build command (run from D:\llama-console):
#   .venv\Scripts\pyinstaller.exe --distpath dist --workpath build -y scripts\NLM_v7.spec
# The --distpath flag is REQUIRED: PyInstaller's default dist folder is
# relative to the spec file's own dir, which would put NLM.exe into
# scripts\dist\ instead of the repo-root dist\ (where it must stay).
import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules, collect_data_files, collect_all

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
    hidden += ['email', 'email.message', 'email.utils', 'email.parser', 'email.feedparser', 'email._policybase', 'email._encoded_words', 'email.charset', 'email.base64mime', 'email.quoprimime', 'urllib', 'urllib.request', 'urllib.parse', 'urllib.error']
hidden += ['app', 'theme', 'main_window', 'backend',
           'pages.console', 'pages.settings', 'pages.dashboard', 'pages.settings_dialog',
           'widgets.card', 'widgets.buttons', 'widgets.chip_icon',
           'widgets.key_value', 'widgets.page_chrome', 'widgets.progress_bar',
           'widgets.server_control', 'widgets.stat_block', 'widgets.status_pill',
           'widgets.elide_label']

# Worker 2026-08-28 17:33 GMT+8 fix (v6 -> v7): bundle pywin32 so hardware.py can use
# win32com.client (WMI CPU model) and win32pdh (live CPU MHz / RAM perf counters)
# instead of falling back to "unknown" when pywin32 is missing from frozen exe.
# pythonnet (LHM PoC) — collect_all 最稳: 埋 clr_loader / pythonnet runtime 全部 datas/binaries
_pn_datas, _pn_binaries, _pn_hidden = collect_all('pythonnet')
hidden += _pn_hidden

hidden += ['win32com', 'win32com.client', 'win32pdh', 'pywintypes', 'pythoncom',
           'win32api', 'win32process', 'win32security', 'win32clipboard',
           'win32com.server', 'win32com.shell', 'win32com.adsi',
           'win32com.bits', 'win32com.client.gencache', 'win32com.client.dynamic',
           'win32com.client.selecttlb', 'win32com.client.util',
           'win32com.server.dispatcher', 'win32com.server.exception',
           'win32com.server.localserver', 'win32com.server.policy',
           'win32com.server.util', 'win32comext', 'win32comext.shell',
           'win32comext.adsi', 'win32comext.shell.shellcon']

a = Analysis(
    [str(v2_root / '__main__.py')],
    pathex=[str(v2_parent)],
    binaries=_pn_binaries,
    datas=[(r'D:\\llama-console\\.venv\\Lib\\site-packages\\certifi\\cacert.pem', 'certifi'),
           (r'D:\\llama-console\\assets\\LlamaDeck.ico', 'assets'),
           (r'D:\\services\\lhm\\LibreHardwareMonitorLib.dll', '.')] + _pn_datas,
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
        'tkinter', 'unittest', 'xml', 'pydoc', 'doctest',
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
    name='LlamaDeck',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=True,
    hide_console='hide-early',  # Quinn 16:06 fix: hide bootloader console during PyInstaller 6.16.0 re-launch
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(Path(r'D:\llama-console\assets\LlamaDeck.ico')),
)