import logging
import os
import sys
import traceback
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

from PySide6.QtCore import QLockFile, QTimer
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from tadris.config import backup_dir, db_override, db_path, documents_dir, log_dir
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
from tadris.services import auth, backup, clock, documents, sessions, subscriptions
from tadris.ui.first_run import FirstRunDialog
from tadris.ui.login_dialog import LoginDialog
from tadris.ui.main_window import MainWindow
from tadris.ui.theme import app_icon, apply_theme, load_fonts
from tadris.ui.user_dialog import show_new_recovery_code

log = logging.getLogger("tadris")
LOG_FILE = "tadris.log"
LOG_BYTES, LOG_COPIES = 1_000_000, 3  # tadris.log, then .1 to .3: a few MB at most
_said: set[tuple[str, str, int]] = set()  # the unexpected errors already shown


def start_log(folder: Path) -> Path:
    """The app's log, in a file: the packaged app has no console, and without it an error
    nobody caught would leave no trace. Also on the console when there is one. Every error
    nobody caught goes there (unexpected())."""
    for handler in list(log.handlers):
        log.removeHandler(handler)
        handler.close()
    path = folder / LOG_FILE
    to_file = RotatingFileHandler(path, maxBytes=LOG_BYTES, backupCount=LOG_COPIES,
                                  encoding="utf-8")
    to_file.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(to_file)
    if sys.stderr is not None:  # None in the packaged app
        log.addHandler(logging.StreamHandler(sys.stderr))
    log.setLevel(logging.INFO)
    sys.excepthook = lambda kind, error, trace: unexpected(kind, error, trace, path)
    return path


def unexpected(kind, error, trace, path: Path) -> None:
    """An error nobody caught. Qt keeps the app running after it: it is written to the log
    and the user is told once, with the file to send. Once per place in the code: an error
    while a list is drawn comes back at every repaint."""
    if issubclass(kind, KeyboardInterrupt):
        sys.__excepthook__(kind, error, trace)
        return
    log.error("Erreur inattendue", exc_info=(kind, error, trace))
    frames = traceback.extract_tb(trace)
    where = (kind.__name__, frames[-1].filename, frames[-1].lineno or 0) if frames else (
        kind.__name__, "", 0)
    if where in _said or QApplication.instance() is None:
        return
    _said.add(where)
    QMessageBox.critical(QApplication.activeWindow(), t["crash.title"],
                         t["crash.text"].format(path=path))


def lock_database(path: Path) -> QLockFile | None:
    """One Tadris at a time on a database: a second one would run the start-of-day jobs and
    the backups again beside the first. tadris.lock next to it, freed when the app closes
    (or found stale by Qt after a crash). None when it is taken."""
    lock = QLockFile(str(path.with_suffix(".lock")))
    lock.setStaleLockTime(0)  # never broken for its age: only when its app is gone
    return lock if lock.tryLock(100) else None


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
        log.warning("%s : valeur ignorée (%s)", SCALE_ENV, value)
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
        log.warning("Nettoyage des documents impossible : %s", exc)


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


def _when(moment: datetime) -> str:
    return t["clock.when"].format(day=moment.strftime("%d/%m/%Y"),
                                  time=moment.strftime("%H:%M"))


def clock_message(result: clock.ClockCheck) -> str:
    return t[f"clock.{result.state}"].format(now=_when(result.now), last=_when(result.last),
                                             days=(result.now - result.last).days)


def _go_on_anyway(text: str, parent=None) -> bool:
    """« Quitter » (the default) or « Continuer quand même »: True for the second."""
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Warning)
    box.setWindowTitle(t["clock.title"])
    box.setText(text)
    leave = box.addButton(t["clock.quit"], QMessageBox.ButtonRole.RejectRole)
    box.addButton(t["clock.go_on"], QMessageBox.ButtonRole.AcceptRole)
    box.setDefaultButton(leave)
    box.exec()
    return box.clickedButton() is not leave


def clock_is_right(conn, parent=None) -> bool:
    """The computer's date against the last operation saved (services/clock), before
    anything is dated by it. False when the user chose « Quitter »."""
    result = clock.check(conn, datetime.now())
    if result.state == "ok":
        return True
    if not _go_on_anyway(clock_message(result), parent):
        return False
    clock.went_on(conn, result)
    return True


def start_of_day(conn) -> None:
    """At start, and again after a restore (the copy may be days old)."""
    subscriptions.mark_ended(conn)  # months whose last day has passed
    sessions.generate_at_start(conn)  # the next 14 days from the timetable


def main() -> int:
    override = db_override()
    if override is not None and not override.exists():
        # Before the log: it would go next to a database that is not there.
        print(f"TADRIS_DB : base introuvable ({override})", file=sys.stderr)
        return 1
    start_log(log_dir())
    _choose_linux_platform()
    _choose_scale()
    app = QApplication(sys.argv)
    app.setApplicationName(t["app.name"])
    app.setWindowIcon(app_icon())
    load_fonts()
    apply_theme(app)

    lock = lock_database(db_path())  # held until main() returns
    if lock is None:
        QMessageBox.information(None, t["app.name"], t["app.already_open"])
        return 1
    conn = connect(db_path())
    folder = backup_dir()
    if not open_database(conn, folder):
        return 1
    if not clock_is_right(conn):
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
    first_run = auth.user_count(conn) == 0
    dialog = FirstRunDialog(conn) if first_run else LoginDialog(conn)
    code = None
    while dialog.exec() == QDialog.DialogCode.Accepted:
        window = MainWindow(conn, dialog.ctx)
        if override is not None:  # never mistake a test copy for the real school
            window.setWindowTitle(f"{window.windowTitle()} · {override.name}")
        _fit_to_screen(window)
        if first_run:  # the director's way back in, written down from the first day
            first_run = False
            show_new_recovery_code(conn, dialog.ctx, window)
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
