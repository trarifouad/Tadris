"""Build the packaged Tadris for the system this runs on. PyInstaller does not build for
another system: the Windows exe and its installer are built on Windows (or by the
« Windows build » workflow on GitHub).

    python packaging/build.py                  # the app, checked, then the installer (Windows)
    python packaging/build.py --no-installer   # the app only

1. PyInstaller, from packaging/tadris.spec: dist/Tadris/ (Tadris.exe and _internal/).
2. The bundle is checked: every migration, font and icon of src/tadris is in it.
3. On Windows, Inno Setup 6 (ISCC.exe) makes dist/Tadris-<version>-setup.exe.

Then `python packaging/smoke_test.py` starts the built app on an empty database.
"""

import argparse
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "src" / "tadris"
DIST = ROOT / "dist"
BUNDLE = DIST / "Tadris"
BUNDLED = BUNDLE / "_internal" / "tadris"
CHECKED = ("db/migrations", "ui/resources/fonts", "ui/resources/icons")
ISCC_PLACES = (r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
               r"C:\Program Files\Inno Setup 6\ISCC.exe")


def app_version() -> str:
    """tadris.__version__, which must say what pyproject.toml says."""
    sys.path.insert(0, str(ROOT / "src"))
    from tadris import __version__

    with open(ROOT / "pyproject.toml", "rb") as file:
        declared = tomllib.load(file)["project"]["version"]
    if declared != __version__:
        raise SystemExit(f"Version mismatch: pyproject.toml says {declared}, "
                         f"src/tadris/__init__.py says {__version__}")
    return __version__


def pyinstaller() -> None:
    subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
                    "--distpath", str(DIST), "--workpath", str(ROOT / "build"),
                    str(ROOT / "packaging" / "tadris.spec")], check=True)


def check_bundle() -> None:
    """The app reads these from its own folder: one missing breaks it only when it is
    needed (a font, an icon) or at the first start (a migration)."""
    missing = [f"{folder}/{file.name}"
               for folder in CHECKED
               for file in sorted((PACKAGE / folder).iterdir())
               if file.is_file() and not (BUNDLED / folder / file.name).is_file()]
    if missing:
        raise SystemExit("Missing from the bundle:\n  " + "\n  ".join(missing))
    counts = ", ".join(f"{len(list((BUNDLED / folder).iterdir()))} in {folder}"
                       for folder in CHECKED)
    print(f"Bundle checked: {counts}")


def inno_setup() -> str | None:
    found = shutil.which("ISCC") or shutil.which("iscc")
    return found or next((place for place in ISCC_PLACES if Path(place).is_file()), None)


def installer(version: str) -> Path:
    compiler = inno_setup()
    if compiler is None:
        raise SystemExit("Inno Setup 6 not found (ISCC.exe). Install it from "
                         "https://jrsoftware.org/isdl.php, or build with --no-installer.")
    subprocess.run([compiler, f"/DAppVersion={version}",
                    str(ROOT / "packaging" / "windows" / "tadris.iss")], check=True)
    return DIST / f"Tadris-{version}-setup.exe"


def size_mb(folder: Path) -> float:
    return sum(f.lstat().st_size for f in folder.rglob("*")
               if f.is_file() and not f.is_symlink()) / 1_000_000


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--no-installer", action="store_true",
                        help="build the app folder only (no Inno Setup)")
    args = parser.parse_args()
    version = app_version()
    pyinstaller()
    check_bundle()
    print(f"App: {BUNDLE} ({size_mb(BUNDLE):.0f} MB), version {version}")
    if args.no_installer:
        return
    if sys.platform != "win32":
        print("Installer: only on Windows (Inno Setup).")
        return
    setup = installer(version)
    print(f"Installer: {setup} ({setup.stat().st_size / 1_000_000:.0f} MB)")


if __name__ == "__main__":
    main()
