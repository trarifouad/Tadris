from PySide6.QtCore import Qt
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
from tadris.ui.widgets.common import ErrorBanner, ask, fit_to_content, labeled, primary_button
from tadris.ui.widgets.forms import caption


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


class PasswordDialog(QDialog):
    """A new password: one's own (the current one is asked first), or another user's,
    reset by the director for someone who forgot theirs."""

    def __init__(self, conn, ctx: UserContext, user_id: int, username: str, parent=None):
        super().__init__(parent)
        self._conn = conn
        self._ctx = ctx
        self._user_id = user_id
        own = user_id == ctx.user_id
        heading = (t["password_dialog.own"] if own
                   else t["password_dialog.reset"].format(username=username))
        self.setWindowTitle(heading)
        self.setFixedWidth(480)

        title = QLabel(heading)
        title.setObjectName("dialogTitle")
        self.banner = ErrorBanner()
        self.current = QLineEdit() if own else None
        self.password = QLineEdit()
        self.password_confirm = QLineEdit()
        for field in (self.current, self.password, self.password_confirm):
            if field is not None:
                field.setEchoMode(QLineEdit.EchoMode.Password)

        self.cancel = QPushButton(t["action.cancel"])
        self.cancel.clicked.connect(self.reject)
        self.submit = primary_button(t["password_dialog.submit"])
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
        if own:
            layout.addWidget(labeled(t["password_dialog.current"], self.current))
        else:
            note = caption(t["password_dialog.reset_note"].format(username=username))
            note.setWordWrap(True)
            layout.addWidget(note)
        layout.addWidget(labeled(t["password_dialog.new"], self.password))
        layout.addWidget(labeled(t["password_dialog.confirm"], self.password_confirm))
        layout.addSpacing(4)
        layout.addLayout(actions)
        fit_to_content(self)
        (self.current or self.password).setFocus()

    def _submit(self) -> None:
        self.banner.clear_error()
        if self.password.text() != self.password_confirm.text():
            self.banner.show_error(t["auth.password_mismatch"])
            self.password_confirm.clear()
            self.password_confirm.setFocus()
            return
        try:
            auth.change_password(self._conn, self._ctx, self._user_id, self.password.text(),
                                 self.current.text() if self.current is not None else None)
        except BusinessRuleError as exc:
            self.banner.show_error(exc.message)
            return
        self.accept()


class RecoveryCodeDialog(QDialog):
    """A new recovery code, shown this once to be written down."""

    def __init__(self, code: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(t["recovery_code.title"])
        self.setFixedWidth(480)
        title = QLabel(t["recovery_code.title"])
        title.setObjectName("dialogTitle")
        self.code = QLabel(code)
        self.code.setObjectName("recoveryCode")
        self.code.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        note = caption(t["recovery_code.text"])
        note.setWordWrap(True)
        # Not self.done: that is QDialog.done(), which accept() calls.
        self.noted = primary_button(t["recovery_code.done"])
        self.noted.clicked.connect(self.accept)
        actions = QHBoxLayout()
        actions.addStretch()
        actions.addWidget(self.noted)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(16)
        layout.addWidget(title)
        layout.addWidget(self.code)
        layout.addWidget(note)
        layout.addSpacing(4)
        layout.addLayout(actions)
        fit_to_content(self)


def show_new_recovery_code(conn, ctx: UserContext, parent=None) -> str:
    """Make a recovery code (it replaces the old one) and show it to be written down."""
    code = auth.new_recovery_code(conn, ctx)
    ask(RecoveryCodeDialog(code, parent))
    return code


class RecoveryDialog(QDialog):
    """« Mot de passe oublié ? » at login: a director's new password, with the recovery
    code. `ctx`: the director, logged in, once accepted."""

    def __init__(self, conn, username: str = "", parent=None):
        super().__init__(parent)
        self._conn = conn
        self.ctx: UserContext | None = None
        self.setWindowTitle(t["recovery.title"])
        self.setFixedWidth(480)

        title = QLabel(t["recovery.title"])
        title.setObjectName("dialogTitle")
        note = caption(t["recovery.caption"])
        note.setWordWrap(True)
        self.banner = ErrorBanner()
        self.username = QLineEdit(username.strip())
        self.code = QLineEdit()
        self.code.setPlaceholderText("XXXX-XXXX-XXXX-XXXX")
        self.password = QLineEdit()
        self.password_confirm = QLineEdit()
        for field in (self.password, self.password_confirm):
            field.setEchoMode(QLineEdit.EchoMode.Password)

        self.cancel = QPushButton(t["action.cancel"])
        self.cancel.clicked.connect(self.reject)
        self.submit = primary_button(t["recovery.submit"])
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
        layout.addWidget(note)
        layout.addWidget(self.banner)
        layout.addWidget(labeled(t["recovery.username"], self.username))
        layout.addWidget(labeled(t["recovery.code"], self.code))
        layout.addWidget(labeled(t["recovery.password"], self.password))
        layout.addWidget(labeled(t["recovery.confirm"], self.password_confirm))
        layout.addSpacing(4)
        layout.addLayout(actions)
        fit_to_content(self)
        (self.code if self.username.text() else self.username).setFocus()

    def _submit(self) -> None:
        self.banner.clear_error()
        if self.password.text() != self.password_confirm.text():
            self.banner.show_error(t["auth.password_mismatch"])
            self.password_confirm.clear()
            self.password_confirm.setFocus()
            return
        try:
            self.ctx = auth.recover(self._conn, self.username.text(), self.code.text(),
                                    self.password.text())
        except BusinessRuleError as exc:
            self.banner.show_error(exc.message)
            return
        self.accept()
