from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialog, QLabel, QLineEdit, QMessageBox, QVBoxLayout

from tadris.core.context import UserContext
from tadris.core.errors import BusinessRuleError
from tadris.i18n.fr import t
from tadris.services import auth, settings
from tadris.ui.user_dialog import RecoveryDialog
from tadris.ui.widgets.common import (
    ErrorBanner,
    ask,
    brand_row,
    fit_to_content,
    labeled,
    primary_button,
    variant_button,
)


class LoginDialog(QDialog):
    def __init__(self, conn, parent=None):
        super().__init__(parent)
        self._conn = conn
        self.ctx: UserContext | None = None
        self.setWindowTitle(f"{t['app.name']} · {t['login.title']}")
        self.setFixedWidth(480)

        title = QLabel(t["login.title"])
        title.setObjectName("dialogTitle")
        caption = QLabel(settings.get(conn, "school.name") or t["login.caption"])
        caption.setObjectName("caption")

        self.banner = ErrorBanner()
        self.username = QLineEdit()
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.submit = primary_button(t["login.submit"])
        self.submit.clicked.connect(self._submit)
        # Enter goes down the form, as at a desk: the username, then the password, then it
        # logs in. Not a default button, which Enter in the username field would press.
        self.submit.setDefault(False)
        self.submit.setAutoDefault(False)
        self.username.returnPressed.connect(self._username_entered)
        self.password.returnPressed.connect(self._password_entered)
        self.forgot = variant_button(t["login.forgot"], "ghost")
        self.forgot.clicked.connect(self._forgot)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(16)
        layout.addLayout(brand_row())
        heading = QVBoxLayout()
        heading.setSpacing(2)
        heading.addWidget(title)
        heading.addWidget(caption)
        layout.addLayout(heading)
        layout.addWidget(self.banner)
        layout.addWidget(labeled(t["login.username"], self.username))
        layout.addWidget(labeled(t["login.password"], self.password))
        layout.addSpacing(4)
        layout.addWidget(self.submit)
        layout.addWidget(self.forgot, 0, Qt.AlignmentFlag.AlignHCenter)
        fit_to_content(self)
        self.username.setFocus()

    def _username_entered(self) -> None:
        if self.username.text().strip() and self.password.text():
            self._submit()
        else:
            self.password.setFocus()

    def _password_entered(self) -> None:
        if not self.username.text().strip():
            self.username.setFocus()
        elif self.password.text():
            self._submit()

    def _submit(self) -> None:
        self.banner.clear_error()
        self.submit.setEnabled(False)
        # login() may pause after repeated failures; show that the app is working.
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self.ctx = auth.login(self._conn, self.username.text(), self.password.text())
        except BusinessRuleError as exc:
            self.banner.show_error(exc.message)
            self.password.clear()
            self.password.setFocus()
            return
        finally:
            QApplication.restoreOverrideCursor()
            self.submit.setEnabled(True)
        self.accept()

    def _forgot(self) -> None:
        """A director's new password with the recovery code; then they are logged in."""
        dialog = RecoveryDialog(self._conn, self.username.text(), self)
        if not ask(dialog):
            return
        QMessageBox.information(self, t["recovery.done_title"], t["recovery.done"])
        self.ctx = dialog.ctx
        self.accept()
