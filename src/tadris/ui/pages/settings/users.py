"""Paramètres → Utilisateurs: the accounts that can log in on this computer."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from tadris.core.context import UserContext
from tadris.core.dates import display_date
from tadris.i18n.fr import t
from tadris.services import auth
from tadris.ui.user_dialog import UserDialog
from tadris.ui.widgets.common import ask, primary_button, toast
from tadris.ui.widgets.compact import section_card
from tadris.ui.widgets.forms import caption
from tadris.ui.widgets.tables import fill, item, ruled_table


class UsersSection(QWidget):
    def __init__(self, conn, ctx: UserContext):
        super().__init__()
        self._conn = conn
        self._ctx = ctx

        title = QLabel(t["settings.section.users"])
        title.setObjectName("sectionTitle")
        note = caption(t["users.caption"])
        note.setWordWrap(True)
        self.new_user = primary_button(t["users.new"])
        self.new_user.setDefault(False)
        self.new_user.clicked.connect(self._create_user)
        names = QVBoxLayout()
        names.setSpacing(2)
        names.addWidget(title)
        names.addWidget(note)
        head = QHBoxLayout()
        head.addLayout(names, 1)
        head.addWidget(self.new_user, 0, Qt.AlignmentFlag.AlignTop)

        self.table = ruled_table([
            t["users.col.username"],
            t["users.col.role"],
            t["users.col.status"],
            t["users.col.created"],
        ])
        # As tall as its rows (refresh): the card ends with the list, nothing stretched.
        self.table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        card = section_card()
        card.layout().addLayout(head)
        card.layout().addWidget(self.table)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(card)
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
        rows = self.table.rowCount()
        header = self.table.horizontalHeader().sizeHint().height()
        self.table.setFixedHeight(header + 2 + rows * self.table.verticalHeader()
                                  .defaultSectionSize())

    def _create_user(self) -> None:
        dialog = UserDialog(self._conn, self._ctx, self)
        if not ask(dialog):
            return
        self.refresh()
        toast(self, t["users.created"].format(username=dialog.username.text().strip()))
