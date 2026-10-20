import os
import sys

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from tadris.config import backup_dir, db_override, db_path
from tadris.db.connection import connect
from tadris.db.migrate import has_pending, migrate
from tadris.i18n.fr import t
from tadris.services import auth, backup, sessions, subscriptions
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


def _backup(take, parent=None, warning: str = "backup.warning") -> bool:
    """Run a backup; on failure warn the user (never block the desk). True if it worked."""
    try:
        take()
    except backup.BackupFailed as exc:
        QMessageBox.warning(parent, t["backup.warning_title"],
                            t[warning].format(error=exc.message))
        return False
    return True


def main() -> int:
    _choose_linux_platform()
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
    if has_pending(conn) and not _backup(lambda: backup.take(conn, folder),
                                         warning="backup.before_migration"):
        return 1  # never migrate a database without a copy taken just before
    migrate(conn)
    _backup(lambda: backup.daily(conn, folder))
    subscriptions.mark_ended(conn)  # months whose last day has passed
    sessions.generate_at_start(conn)  # the next 14 days from the timetable

    dialog = FirstRunDialog(conn) if auth.user_count(conn) == 0 else LoginDialog(conn)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return 0

    window = MainWindow(conn, dialog.ctx)
    if override is not None:  # never mistake a test copy for the real school
        window.setWindowTitle(f"{window.windowTitle()} · {override.name}")
    window.show()
    timer = QTimer(window)
    timer.timeout.connect(lambda: _backup(lambda: backup.daily(conn, folder), window))
    timer.start(DAILY_CHECK_MS)
    code = app.exec()
    _backup(lambda: backup.take(conn, folder))  # the day's work, on close
    return code
