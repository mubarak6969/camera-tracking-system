# PyInstaller build configuration for AI Focus Tracker.
#
# Build with:
#     .venv\Scripts\pyinstaller AIFocusTracker.spec
#
# Produces dist/AIFocusTracker/AIFocusTracker.exe - a self-contained build
# with its own Python, Qt (PySide6), OpenCV, and pywin32, so it never
# depends on the development .venv or a system Python install at runtime.
#
# Why each extra piece below is here:
# - OpenCV's Haar cascade XML files live under cv2/data/ inside the
#   installed cv2 package and are NOT Python modules, so PyInstaller's
#   static import analysis cannot find them on its own - they must be
#   listed explicitly in `datas`, or face detection silently fails to
#   load its classifier in the frozen build.
# - pynput and pywin32 both do some of their platform-specific module
#   selection dynamically (by OS at import time) rather than with a plain
#   top-level `import`, which can make PyInstaller's static analyzer miss
#   a module it does not statically see referenced. Listing the concrete
#   Windows backends in `hiddenimports` is cheap insurance against a
#   "no module named ..." failure that would otherwise only show up when
#   the frozen executable is actually run.
from pathlib import Path

import cv2

block_cipher = None

_cv2_data_dir = Path(cv2.data.haarcascades)  # ends in cv2/data/ - bundle the whole folder

datas = [
    (str(_cv2_data_dir), "cv2/data"),
]

hiddenimports = [
    # pywin32 - focus_tracker/platform_win/session_monitor.py imports these
    # lazily at runtime, so PyInstaller's static scan never sees them.
    "win32api",
    "win32con",
    "win32gui",
    "win32ts",
    "win32timezone",
    # pynput's concrete Windows backends, selected dynamically by pynput
    # itself based on sys.platform.
    "pynput.keyboard._win32",
    "pynput.mouse._win32",
]

a = Analysis(
    ["app.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="AIFocusTracker",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,  # no console window - this is a tray/background desktop app
    disable_windowed_traceback=False,
    argv_emulation=False,
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
    upx=False,
    upx_exclude=[],
    name="AIFocusTracker",
)
