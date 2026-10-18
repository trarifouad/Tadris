from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from tadris.core.context import UserContext
from tadris.core.dates import display_date
from tadris.i18n.fr import t
from tadris.services import auth
from tadris.ui.user_dialog import UserDialog
from tadris.ui.widgets.common import primary_button, toast
from tadris.ui.widgets.tables import fill, item, ruled_table


class SettingsPage(QWidget):
    """Director-only settings. Phase 1 holds the user accounts; school details come later."""

    def __init__(self, conn, ctx: UserContext):
        super().__init__()
        self._conn = conn
        self._ctx = ctx
        self.setObjectName("page")

        heading = QLabel(t["nav.settings"])
        heading.setObjectName("pageTitle")

        section_title = QLabel(t["users.title"])
        section_title.setObjectName("sectionTitle")
        section_caption = QLabel(t["users.caption"])
        section_caption.setObjectName("caption")
        section_text = QVBoxLayout()
        section_text.setSpacing(2)
        section_text.addWidget(section_title)
        section_text.addWidget(section_caption)
        self.new_user = primary_button(t["users.new"])
        self.new_user.setDefault(False)
        self.new_user.clicked.connect(self._create_user)
        section_head = QHBoxLayout()
        section_head.addLayout(section_text)
        section_head.addStretch()
        section_head.addWidget(self.new_user, alignment=Qt.AlignmentFlag.AlignBottom)

        self.table = ruled_table([
            t["users.col.username"],
            t["users.col.role"],
            t["users.col.status"],
            t["users.col.created"],
        ])

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 24)
        layout.setSpacing(16)
        layout.addWidget(heading)
        layout.addSpacing(4)
        layout.addLayout(section_head)
        layout.addWidget(self.table, 1)
        self.refresh()

    def refresh(self) -> None:
        users = auth.list_users(self._conn, self._ctx)
        fill(self.table, [
            [
                item(user["username"]),
                item(t[f"role.{user['role']}"]),
                item(t[f"user_status.{user['status']}"]),
                item(display_date(user["created_at"])),
            ]
            for user in users
        ])

    def _create_user(self) -> None:
        dialog = UserDialog(self._conn, self._ctx, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self.refresh()
        message = t["users.created"].format(username=dialog.username.text().strip())
        toast(self, message)
