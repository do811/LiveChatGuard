# -*- mode: python ; coding: utf-8 -*-
"""LiveChatGuard PyInstaller config.

Build with build_release.bat. Set LCG_ONEFILE=1 for a single EXE,
LCG_CONSOLE=1 to show a console for debugging.
"""
import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files

ROOT = Path(SPECPATH).resolve()
ONEFILE = os.environ.get('LCG_ONEFILE', '0') == '1'
CONSOLE = os.environ.get('LCG_CONSOLE', '0') == '1'

# The keyring backend is selected dynamically on Windows. googleapiclient
# dynamically loads discovery definitions. Both need special collection.
keyring_datas, keyring_binaries, keyring_hidden = collect_all('keyring')
youtube_datas, youtube_binaries, youtube_hidden = collect_all('googleapiclient')

bundled_datas = (
    keyring_datas
    + youtube_datas
    + collect_data_files('tzdata')  # zoneinfo: America/Los_Angeles on Windows
    + collect_data_files('certifi')
)
bundled_binaries = keyring_binaries + youtube_binaries
hidden_imports = sorted(set(keyring_hidden + youtube_hidden + [
    'keyring.backends.Windows',
    'keyring.backends.fail',
    'google_auth_oauthlib.flow',
    'google.auth.transport.requests',
    'google.oauth2.credentials',
    'googleapiclient.discovery_cache',
]))

a = Analysis(
    [str(ROOT / 'livechat_guard_launcher.py')],
    pathex=[str(ROOT / 'src')],
    binaries=bundled_binaries,
    datas=bundled_datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['pytest', 'ruff'],
    noarchive=False,
)
pyz = PYZ(a.pure)

if ONEFILE:
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.datas,
        [],
        name='LiveChatGuard',
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        console=CONSOLE,
        disable_windowed_traceback=False,
    )
else:
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name='LiveChatGuard',
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        console=CONSOLE,
        disable_windowed_traceback=False,
    )
    coll = COLLECT(
        exe,
        a.binaries,
        a.datas,
        strip=False,
        upx=False,
        name='LiveChatGuard',
    )
