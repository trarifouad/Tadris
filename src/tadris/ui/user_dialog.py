from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from tadris.core.context import UserContext
from tadris.core.errors import BusinessRuleError
from tadris.i18n.fr import t
from tadris.services import auth
from tadris.ui.widgets.common import ErrorBanner, fit_to_content, labeled, primary_button


class UserDialog(QDialog):
    """Director creates a login for the front desk or another director."""

    def __init__(self, conn, ctx: UserContext, parent=None):
        super().__init__(parent)
        self._conn = conn
        self._ctx = ctx
        self.user_id: int | None = None
        self.setWindowTitle(t["user_dialog.title"])
        self.setFixedWidth(480)

        title = QLabel(t["user_dialog.title"])
        title.setObjectName("dialogTitle")
        self.banner = ErrorBanner()
        self.username = QLineEdit()
        self.password = QLineEdit()
        self.password_confirm = QLineEdit()
        for field in (self.password, self.password_confirm):
            field.setEchoMode(QLineEdit.EchoMode.Password)
        self.role = QComboBox()
        self.role.addItem(t["role.receptionist"], "receptionist")
        self.role.addItem(t["role.director"], "director")

        self.cancel = QPushButton(t["action.cancel"])
        self.cancel.clicked.connect(self.reject)
        self.submit = primary_button(t["user_dialog.submit"])
        self.submit.clicked.connect(self._submit)
        actions = QHBoxLayout()
        actions.setSpacing(8)
        actions.addStretch()
        actions.addWidget(self.cancel)
        actions.addWidget(self.submit)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(16)
        layout.addWidget(title)
        layout.addWidget(self.banner)
        layout.addWidget(labeled(t["user_dialog.username"], self.username))
        layout.addWidget(labeled(t["user_dialog.role"], self.role))
        layout.addWidget(labeled(t["user_dialog.password"], self.password))
        layout.addWidget(labeled(t["user_dialog.password_confirm"], self.password_confirm))
        layout.addSpacing(4)
        layout.addLayout(actions)
        fit_to_content(self)
        self.username.setFocus()

    def _submit(self) -> None:
        self.banner.clear_error()
        if self.password.text() != self.password_confirm.text():
            self.banner.show_error(t["auth.password_mismatch"])
            self.password_confirm.clear()
            self.password_confirm.setFocus()
            return
        try:
            self.user_id = auth.create_user(
                self._conn,
                self._ctx,
                self.username.text(),
                self.password.text(),
                self.role.currentData(),
            )
        except BusinessRuleError as exc:
            self.banner.show_error(exc.message)
            return
        self.accept()
