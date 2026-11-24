# PyInstaller (one-dir) — Organizer masaüstü. CI: cd masaustu && pyinstaller --noconfirm organizer.spec
# Çıktı: dist/Organizer/Organizer.exe + dist/Organizer/_internal/ (assets, fccore yazı tipleri, Qt)
# win-app kanalı bu klasörün fcpack zip'idir (python -m fccore.fcpack dist/Organizer Organizer-win-app.zip).
import os

HERE = os.path.abspath(SPECPATH)  # noqa: F821
datas = [(os.path.join(HERE, 'assets'), 'assets'), (os.path.join(HERE, 'fccore', 'fonts'), os.path.join('fccore', 'fonts'))]

a = Analysis(  # noqa: F821
    [os.path.join(HERE, 'main.py')],
    pathex=[HERE],
    datas=datas,
    hiddenimports=['PySide6.QtSvg', 'organizer.app'],
    excludes=['tkinter', 'PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets', 'PySide6.Qt3DCore', 'PySide6.QtQuick',
              'PySide6.QtQml', 'PySide6.QtPdf', 'PySide6.QtMultimedia', 'PySide6.QtCharts', 'PySide6.QtDataVisualization'],
    noarchive=False,
)
pyz = PYZ(a.pure)  # noqa: F821
exe = EXE(  # noqa: F821
    pyz, a.scripts, [], exclude_binaries=True, name='Organizer', icon=os.path.join(HERE, 'assets', 'logo.ico'),
    console=False, debug=False, strip=False, upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name='Organizer', strip=False, upx=False)  # noqa: F821
