# PyInstaller spec for Tadris: one folder, dist/Tadris/, with Tadris(.exe) and _internal/.
# Built by packaging/build.py (python packaging/build.py), not by hand.
#
# The app finds its migrations, fonts and icons from its own files (Path(__file__)), so
# they go in _internal/tadris/ at the same places as in src/tadris/: no code change for
# the frozen app. One folder rather than one file: it starts faster, and an antivirus is
# less suspicious of it than of an exe that unpacks itself into a temporary folder.

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH).parent  # noqa: F821 - SPECPATH is given by PyInstaller
SRC = ROOT / "src"
PACKAGE = SRC / "tadris"
sys.path.insert(0, str(SRC))
from tadris import __version__  # noqa: E402

datas = [
    (str(PACKAGE / "db" / "migrations"), "tadris/db/migrations"),
    (str(PACKAGE / "ui" / "resources"), "tadris/ui/resources"),
]

# Imported by name at run time, so PyInstaller's analysis misses them: reportlab's barcode
# widgets (the QR code) load each barcode module from a string. packaging/check_imports.py
# finds any other such module the tests load.
hiddenimports = collect_submodules("reportlab.graphics.barcode")

# Never used by Tadris, but found by PyInstaller's analysis through the libraries.
excludes = ["tkinter", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets",
            "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtPdf", "PySide6.QtMultimedia"]


def windows_version_info():
    """The exe's file properties (version, description). Windows only: the module that
    writes them needs pefile, which PyInstaller installs on Windows alone."""
    from PyInstaller.utils.win32 import versioninfo as vi

    numbers = tuple(int(part) for part in __version__.split(".")) + (0,)
    return vi.VSVersionInfo(
        ffi=vi.FixedFileInfo(filevers=numbers, prodvers=numbers),
        kids=[
            vi.StringFileInfo([vi.StringTable("040C04B0", [  # French, Unicode
                vi.StringStruct("CompanyName", "Tadris"),
                vi.StringStruct("FileDescription", "Tadris, gestion de l'école de soutien"),
                vi.StringStruct("FileVersion", __version__),
                vi.StringStruct("InternalName", "Tadris"),
                vi.StringStruct("OriginalFilename", "Tadris.exe"),
                vi.StringStruct("ProductName", "Tadris"),
                vi.StringStruct("ProductVersion", __version__),
            ])]),
            vi.VarFileInfo([vi.VarStruct("Translation", [0x040C, 1200])]),
        ],
    )


a = Analysis(  # noqa: F821
    [str(PACKAGE / "__main__.py")],
    pathex=[str(SRC)],
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=excludes,
    noarchive=False,
)
pyz = PYZ(a.pure)  # noqa: F821

exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Tadris",
    console=False,  # no console window: errors go to logs/tadris.log
    icon=str(ROOT / "packaging" / "tadris.ico"),
    version=windows_version_info() if sys.platform == "win32" else None,
    upx=False,  # UPX-packed files are a classic antivirus false alarm
)

coll = COLLECT(  # noqa: F821
    exe,
    a.binaries,
    a.datas,
    name="Tadris",
    upx=False,
)
