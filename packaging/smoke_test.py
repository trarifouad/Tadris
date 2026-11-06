"""Start the built app (dist/Tadris/) on an empty database and check that it gets as far
as the first-run wizard, which is what a fresh install does:

- it brings the database to the latest migration (it found its migrations),
- it takes and verifies the day's backup,
- it is still running a few seconds later, with no error in its log (fonts, icons, theme).

Then it is stopped, by its own PID. Nothing of the school's is touched: TADRIS_DB points
to a file in a temporary folder, and its backups and log go next to it.

    python packaging/smoke_test.py               # Linux: needs a display (or xvfb-run)
    python packaging/smoke_test.py --offscreen   # no display at all (Qt's offscreen platform)
"""

import argparse
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "dist" / "Tadris" / ("Tadris.exe" if sys.platform == "win32" else "Tadris")
MIGRATIONS = ROOT / "src" / "tadris" / "db" / "migrations"
STARTUP_S = 120  # a first start on a cold machine is slow (an antivirus scans every file)
SETTLE_S = 5  # still running this long after the database is ready: the wizard is up


def latest_migration() -> int:
    return max(int(file.name[:4]) for file in MIGRATIONS.glob("[0-9][0-9][0-9][0-9]_*.sql"))


def version_of(db: Path) -> int:
    try:
        with closing(sqlite3.connect(db, timeout=1)) as conn:
            return conn.execute("PRAGMA user_version").fetchone()[0]
    except sqlite3.Error:
        return -1  # being migrated: try again


def verified_backups(db: Path) -> int:
    with closing(sqlite3.connect(db, timeout=5)) as conn:
        return conn.execute("SELECT COUNT(*) FROM backups WHERE status = 'verified'").fetchone()[0]


def fail(message: str, folder: Path) -> None:
    print(f"FAILED: {message}")
    for name in ("output.txt", "logs/tadris.log"):
        path = folder / name
        if path.is_file() and path.stat().st_size:
            print(f"--- {name} ---\n{path.read_text(encoding='utf-8', errors='replace')}")
    raise SystemExit(1)


def stop(app: subprocess.Popen) -> None:
    if app.poll() is None:
        app.terminate()
        try:
            app.wait(15)
        except subprocess.TimeoutExpired:
            app.kill()
            app.wait(15)


def run(folder: Path, offscreen: bool) -> None:
    db = folder / "tadris.db"
    db.touch()  # an empty file: the first-run wizard
    env = {**os.environ, "TADRIS_DB": str(db)}
    if offscreen:
        env["QT_QPA_PLATFORM"] = "offscreen"
    latest = latest_migration()
    with open(folder / "output.txt", "w", encoding="utf-8") as output:
        app = subprocess.Popen([str(APP)], env=env, stdout=output, stderr=subprocess.STDOUT)
        try:
            deadline = time.monotonic() + STARTUP_S
            while version_of(db) != latest:
                if app.poll() is not None:
                    fail(f"the app quit (code {app.returncode}) before the database was "
                         f"ready (version {version_of(db)} of {latest})", folder)
                if time.monotonic() > deadline:
                    fail(f"the database is at version {version_of(db)} of {latest} after "
                         f"{STARTUP_S} s", folder)
                time.sleep(0.5)
            time.sleep(SETTLE_S)
            if app.poll() is not None:
                fail(f"the app quit (code {app.returncode}) at the first-run wizard", folder)
        finally:
            stop(app)
    log = folder / "logs" / "tadris.log"
    errors = [line for line in log.read_text(encoding="utf-8").splitlines()
              if " ERROR " in line] if log.is_file() else []
    if errors:
        fail(f"{len(errors)} error(s) in the app's log", folder)
    if verified_backups(db) < 1:
        fail("no verified backup was taken at start", folder)
    print(f"OK: {APP.name} started on an empty database, migrated it to version {latest}, "
          f"took a verified backup and opened the first-run wizard.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--offscreen", action="store_true",
                        help="run without a display (Qt's offscreen platform)")
    args = parser.parse_args()
    if not APP.is_file():
        raise SystemExit(f"{APP} not found: run python packaging/build.py first")
    with tempfile.TemporaryDirectory(prefix="tadris-smoke-") as folder:
        run(Path(folder), args.offscreen)


if __name__ == "__main__":
    main()
