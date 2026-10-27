import os
import sys

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from tadris.config import backup_dir, db_override, db_path, documents_dir
from tadris.db.connection import connect
from tadris.db.migrate import (
    MigrationFailed,
    current_version,
    has_pending,
    is_newer,
    latest_version,
    migrate,
)
from tadris.i18n.fr import t
from tadris.services import auth, backup, documents, sessions, subscriptions
from tadris.ui.first_run import FirstRunDialog
from tadris.ui.login_dialog import LoginDialog
from tadris.ui.main_window import MainWindow
from tadris.ui.theme import apply_theme, load_fonts


def _choose_linux_platform() -> None:
    # Qt's Wayland backend aborts on GNOME 50, whose xsettings schema no longer has the
    # 'antialiasing' key it reads. XWayland (xcb) works. An explicit QT_QPA_PLATFORM wins.
    if sys.platform.startswith("linux"):
        os.environ.setdefault("QT_QPA_PLATFORM", "xcb")


DAILY_CHECK_MS = 60 * 60 * 1000  # the app may stay open past midnight
# The app's own zoom, for Tadris only (the computer's settings are left alone). On Linux it
# defaults to 125 %, the scale most Windows laptops use, so the app looks as it will at the
# school. On Windows Qt already follows the system's scale: nothing is added there, unless
# TADRIS_SCALE asks for it (e.g. TADRIS_SCALE=1 for 100 %, 1.5 for 150 %).
SCALE_ENV = "TADRIS_SCALE"
LINUX_SCALE = "1.25"
MIN_SCALE, MAX_SCALE = 0.5, 3.0


def _choose_scale() -> None:
    """Set before the QApplication exists: Qt reads QT_SCALE_FACTOR once, at start."""
    value = os.environ.get(SCALE_ENV, "").strip().replace(",", ".")
    if value:
        try:
            scale = float(value)
        except ValueError:
            scale = None
        if scale is not None and MIN_SCALE <= scale <= MAX_SCALE:
            os.environ["QT_SCALE_FACTOR"] = str(scale)
            return
        print(f"{SCALE_ENV} : valeur ignorée ({value})", file=sys.stderr)
    if sys.platform.startswith("linux"):
        os.environ.setdefault("QT_SCALE_FACTOR", LINUX_SCALE)


def _fit_to_screen(window) -> None:
    """At 125 % a small screen may be smaller than the window: fill it instead. Its size is
    brought within the screen too, so it still fits once restored from maximized."""
    screen = window.screen().availableGeometry()
    if window.width() > screen.width() or window.height() > screen.height() * 0.95:
        window.resize(window.size().boundedTo(screen.size() * 0.9))
        window.move(screen.center() - window.rect().center())
        window.showMaximized()
    else:
        window.show()


def _backup(take, parent=None, warning: str = "backup.warning") -> bool:
    """Run a backup; on failure warn the user (never block the desk). True if it worked."""
    try:
        take()
    except backup.MirrorFailed as exc:  # the copy is made: only the second one is missing
        QMessageBox.warning(parent, t["backup.warning_title"],
                            t["backup.second_warning"].format(error=exc.message))
    except backup.BackupFailed as exc:
        QMessageBox.warning(parent, t["backup.warning_title"],
                            t[warning].format(error=exc.message))
        return False
    return True


def _clean_documents(conn) -> None:
    """Old working copies of reports and receipts out of the documents folder; a failure
    there never stops the app."""
    try:
        documents.clean_at_start(conn, documents_dir())
    except Exception as exc:  # noqa: BLE001 - the desk must open whatever happens here
        print(f"Nettoyage des documents impossible : {exc}", file=sys.stderr)


def open_database(conn, folder, parent=None) -> bool:
    """Bring the database to this version of the app. False (with a message saying why)
    when the app must not go on: a database from a later version, no copy before a
    migration, or a migration that failed (it changed nothing; the copy is named)."""
    if is_newer(conn):
        QMessageBox.critical(parent, t["migration.title"], t["migration.newer"].format(
            version=current_version(conn), latest=latest_version()))
        return False
    taken = []
    if has_pending(conn) and not _backup(lambda: taken.append(backup.take(conn, folder)),
                                         parent, warning="backup.before_migration"):
        return False  # never migrate a database without a copy taken just before
    try:
        migrate(conn)
    except MigrationFailed as exc:
        copy = taken[0].file_path if taken else t["migration.no_copy"]
        QMessageBox.critical(parent, t["migration.title"], t["migration.failed"].format(
            version=exc.version, error=exc.error, copy=copy))
        return False
    return True


def start_of_day(conn) -> None:
    """At start, and again after a restore (the copy may be days old)."""
    subscriptions.mark_ended(conn)  # months whose last day has passed
    sessions.generate_at_start(conn)  # the next 14 days from the timetable


def main() -> int:
    _choose_linux_platform()
    _choose_scale()
    app = QApplication(sys.argv)
    app.setApplicationName(t["app.name"])
    load_fonts()
    apply_theme(app)

    override = db_override()
    if override is not None and not override.exists():
        print(f"TADRIS_DB : base introuvable ({override})", file=sys.stderr)
        return 1
    conn = connect(db_path())
    folder = backup_dir()
    if not open_database(conn, folder):
        return 1
    _backup(lambda: backup.daily(conn, folder))
    _clean_documents(conn)
    start_of_day(conn)

    code = run_sessions(app, conn, folder, override)
    if code is None:
        return 0  # nobody logged in: nothing to save
    _backup(lambda: backup.take(conn, folder))  # the day's work, on close
    return code


def run_sessions(app, conn, folder, override) -> int | None:
    """Login, the main window, and back to the login screen after « Se déconnecter », until
    the app is quit. None if nobody logged in at all."""
    dialog = FirstRunDialog(conn) if auth.user_count(conn) == 0 else LoginDialog(conn)
    code = None
    while dialog.exec() == QDialog.DialogCode.Accepted:
        window = MainWindow(conn, dialog.ctx)
        if override is not None:  # never mistake a test copy for the real school
            window.setWindowTitle(f"{window.windowTitle()} · {override.name}")
        _fit_to_screen(window)
        timer = QTimer(window)
        timer.timeout.connect(lambda w=window: _backup(lambda: backup.daily(conn, folder), w))
        timer.start(DAILY_CHECK_MS)
        code = app.exec()  # returns when the window closes
        logged_out = window.logging_out
        if window.restored:
            start_of_day(conn)
        window.deleteLater()
        if not logged_out:
            break
        dialog = LoginDialog(conn)
    return code
