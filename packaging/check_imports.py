"""Check that the built app (dist/Tadris/) holds every module the app loads at run time.

PyInstaller finds the imports written in the code. A library that imports a module by its
name at run time (reportlab's barcodes do, for the QR code) is missed, and the packaged
app then fails only when that code runs: printing a receipt at the school. So the whole
test suite runs here, which prints every document and exports every report, and each
module it loaded from the app or its libraries must be in the bundle.

    python packaging/check_imports.py     # after python packaging/build.py
"""

import os
import subprocess
import sys
import tempfile
from importlib.machinery import EXTENSION_SUFFIXES
from pathlib import Path

from PyInstaller.archive.readers import ZlibArchiveReader

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "dist" / "Tadris" / "_internal"
PYZ = ROOT / "build" / "tadris" / "PYZ-00.pyz"
# The app and the libraries it ships. The standard library is left out: the app's own
# imports of it are written in its code, and the tests load many modules the app never does.
SHIPPED = ("tadris", "reportlab", "openpyxl", "et_xmlfile", "PySide6", "shiboken6",
           "platformdirs", "PIL")
# Not looked for: loaded by the tests only (Qt's test module, a pytest plugin), or found
# elsewhere by the frozen app (PySide6.support: shiboken carries its own copy).
IGNORED = ("PySide6.QtTest", "platformdirs.pytest_plugin", "PySide6.support")


def traced_modules() -> set[str]:
    with tempfile.TemporaryDirectory(prefix="tadris-imports-") as folder:
        trace = Path(folder) / "modules.txt"
        env = {**os.environ, "TADRIS_IMPORT_TRACE": str(trace),
               "PYTHONPATH": os.pathsep.join(filter(None, [str(ROOT / "packaging"),
                                                           os.environ.get("PYTHONPATH")]))}
        tests = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "import_trace",
                                "-p", "no:cacheprovider"], cwd=ROOT, env=env)
        if tests.returncode != 0:
            raise SystemExit("The tests failed: fix them before checking the bundle.")
        names = trace.read_text(encoding="utf-8").split()
    return {name for name in names
            if name.split(".")[0] in SHIPPED and not name.startswith(IGNORED)}


def extension_found(name: str) -> bool:
    """A compiled module (PySide6.QtCore, PIL._imaging): a file in the bundle, not in the
    archive."""
    base = BUNDLE.joinpath(*name.split("."))
    return any(base.with_name(base.name + suffix).is_file() for suffix in EXTENSION_SUFFIXES)


def main() -> None:
    if not PYZ.is_file():
        raise SystemExit(f"{PYZ} not found: run python packaging/build.py first")
    archived = set(ZlibArchiveReader(str(PYZ)).toc)
    loaded = traced_modules()
    missing = sorted(name for name in loaded
                     if name not in archived and not extension_found(name))
    if missing:
        raise SystemExit("Loaded by the app, missing from the bundle (add them to "
                         "hiddenimports in packaging/tadris.spec):\n  " + "\n  ".join(missing))
    print(f"Imports checked: the {len(loaded)} modules the tests loaded from the app and "
          f"its libraries are all in the bundle.")


if __name__ == "__main__":
    main()
