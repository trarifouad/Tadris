from PySide6.QtWidgets import QDialog, QLabel, QLineEdit, QVBoxLayout

from tadris.core.context import UserContext
from tadris.core.errors import BusinessRuleError
from tadris.i18n.fr import t
from tadris.services import auth
from tadris.ui.widgets.common import (
    ErrorBanner,
    brand_row,
    fit_to_content,
    labeled,
    primary_button,
)


class FirstRunDialog(QDialog):
    """Shown once, when the database has no user: creates the director and the school name."""

    def __init__(self, conn, parent=None):
        super().__init__(parent)
        self._conn = conn
        self.ctx: UserContext | None = None
        self.setWindowTitle(f"{t['app.name']} · {t['first_run.title']}")
        self.setFixedWidth(480)

        title = QLabel(t["first_run.title"])
        title.setObjectName("dialogTitle")
        caption = QLabel(t["first_run.caption"])
        caption.setObjectName("caption")
        caption.setWordWrap(True)

        self.banner = ErrorBanner()
        self.school_name = QLineEdit()
        self.username = QLineEdit()
        self.password = QLineEdit()
        self.password_confirm = QLineEdit()
        for field in (self.password, self.password_confirm):
            field.setEchoMode(QLineEdit.EchoMode.Password)
        self.submit = primary_button(t["first_run.submit"])
        self.submit.clicked.connect(self._submit)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(16)
        layout.addLayout(brand_row())
        heading = QVBoxLayout()
        heading.setSpacing(4)
        heading.addWidget(title)
        heading.addWidget(caption)
        layout.addLayout(heading)
        layout.addWidget(self.banner)
        layout.addWidget(labeled(t["first_run.school_name"], self.school_name))
        layout.addWidget(labeled(t["first_run.username"], self.username))
        layout.addWidget(labeled(t["first_run.password"], self.password))
        layout.addWidget(labeled(t["first_run.password_confirm"], self.password_confirm))
        layout.addSpacing(4)
        layout.addWidget(self.submit)
        fit_to_content(self)
        self.school_name.setFocus()

    def _submit(self) -> None:
        self.banner.clear_error()
        if self.password.text() != self.password_confirm.text():
            self.banner.show_error(t["auth.password_mismatch"])
            self.password_confirm.clear()
            self.password_confirm.setFocus()
            return
        try:
            self.ctx = auth.bootstrap_director(
                self._conn, self.username.text(), self.password.text(), self.school_name.text()
            )
        except BusinessRuleError as exc:
            self.banner.show_error(exc.message)
            return
        self.accept()
