import sys

from PySide6.QtWidgets import QApplication, QDialog

from tadris.config import db_path
from tadris.db.connection import connect
from tadris.db.migrate import migrate
from tadris.i18n.fr import t
from tadris.services import auth
from tadris.ui.first_run import FirstRunDialog
from tadris.ui.login_dialog import LoginDialog
from tadris.ui.main_window import MainWindow
from tadris.ui.theme import apply_theme, load_fonts


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName(t["app.name"])
    load_fonts()
    apply_theme(app)

    conn = connect(db_path())
    migrate(conn)

    dialog = FirstRunDialog(conn) if auth.user_count(conn) == 0 else LoginDialog(conn)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return 0

    window = MainWindow(conn, dialog.ctx)
    window.show()
    return app.exec()
