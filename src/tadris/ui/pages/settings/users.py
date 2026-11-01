"""Paramètres → Utilisateurs: the accounts that can log in on this computer. The selected
account's actions under the list: a new password (one's own, or reset for someone who
forgot theirs) and disable / enable (someone who left). Under it, the recovery code: the way
back in when a director's password is forgotten (« Mot de passe oublié ? » at login)."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from tadris.core.context import UserContext
from tadris.core.dates import display_date
from tadris.core.errors import BusinessRuleError
from tadris.i18n.fr import t
from tadris.services import auth
from tadris.ui.user_dialog import PasswordDialog, UserDialog, show_new_recovery_code
from tadris.ui.widgets.common import Badge, PageBanner, ask, confirm, primary_button, toast
from tadris.ui.widgets.compact import row_actions_below, section_card, summary_card
from tadris.ui.widgets.forms import caption
from tadris.ui.widgets.tables import fill, item, ruled_table, selected_id


class UsersSection(QWidget):
    def __init__(self, conn, ctx: UserContext):
        super().__init__()
        self._conn = conn
        self._ctx = ctx
        self._users: dict[int, dict] = {}

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
        self.table.itemSelectionChanged.connect(self._update_actions)
        self.password = QPushButton(t["users.password"])
        self.password.clicked.connect(self._change_password)
        self.status = QPushButton(t["users.disable"])
        self.status.clicked.connect(self._toggle_status)
        for button in (self.password, self.status):
            button.setAutoDefault(False)

        self.banner = PageBanner()

        card = section_card()
        card.layout().addLayout(head)
        card.layout().addWidget(self.banner)
        card.layout().addWidget(self.table)
        row_actions_below(self.table, [self.password, self.status], card.layout(),
                          card.layout().indexOf(self.table) + 1)
        recovery, body, self.recovery = summary_card(t["users.recovery"],
                                                     t["users.recovery_new"])
        self.recovery.clicked.connect(self._new_recovery_code)
        self.recovery_todo = Badge(t["users.recovery_todo"], "warning")
        self.recovery_text = caption()
        self.recovery_text.setWordWrap(True)
        state = QHBoxLayout()
        state.setSpacing(8)
        state.addWidget(self.recovery_text, 1)
        state.addWidget(self.recovery_todo, 0, Qt.AlignmentFlag.AlignTop)
        body.addLayout(state)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        layout.addWidget(card)
        layout.addWidget(recovery)
        self.refresh()

    def refresh(self) -> None:
        users = auth.list_users(self._conn, self._ctx)
        self._users = {user["id"]: user for user in users}
        fill(self.table, [
            [
                item(user["username"], item_id=user["id"]),
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
        self._update_actions()
        made = auth.recovery_code_made(self._conn, self._ctx)
        self.recovery_text.setText(t["users.recovery_none"] if made is None
                                   else t["users.recovery_made"].format(date=display_date(made)))
        self.recovery_todo.setVisible(made is None)
        self.recovery.setText(t["users.recovery_new" if made is None else "users.recovery_again"])

    def selected(self) -> dict | None:
        user_id = selected_id(self.table)
        return None if user_id is None else self._users.get(user_id)

    def select(self, username: str) -> None:
        for row in range(self.table.rowCount()):
            if self.table.item(row, 0).text() == username:
                self.table.selectRow(row)
                return

    def _update_actions(self) -> None:
        user = self.selected()
        self.password.setEnabled(user is not None)
        active = user is None or user["status"] == "active"
        self.status.setText(t["users.disable" if active else "users.enable"])
        own = user is not None and user["id"] == self._ctx.user_id
        self.status.setEnabled(user is not None and not own)
        self.status.setToolTip(t["users.self_tip"] if own else "")

    def _create_user(self) -> None:
        dialog = UserDialog(self._conn, self._ctx, self)
        if not ask(dialog):
            return
        self.refresh()
        toast(self, t["users.created"].format(username=dialog.username.text().strip()))

    def _change_password(self) -> None:
        user = self.selected()
        if user is None:
            return
        if ask(PasswordDialog(self._conn, self._ctx, user["id"], user["username"], self)):
            toast(self, t["users.password_changed"].format(username=user["username"]))

    def _toggle_status(self) -> None:
        user = self.selected()
        if user is None:
            return
        self.banner.clear_error()
        username = user["username"]
        try:
            if user["status"] == "active":
                if not confirm(self, t["users.disable_title"],
                               t["users.disable_text"].format(username=username),
                               t["users.disable"]):
                    return
                auth.disable_user(self._conn, self._ctx, user["id"])
                done = t["users.disabled"]
            else:
                auth.enable_user(self._conn, self._ctx, user["id"])
                done = t["users.enabled"]
        except BusinessRuleError as exc:
            self.banner.show_error(exc.message)
            return
        self.refresh()
        self.select(username)
        toast(self, done.format(username=username))

    def _new_recovery_code(self) -> None:
        """A new code replaces the old one, which stops working: asked first."""
        if (auth.recovery_code_made(self._conn, self._ctx) is not None
                and not confirm(self, t["users.recovery_replace_title"],
                                t["users.recovery_replace"], t["users.recovery_again"])):
            return
        show_new_recovery_code(self._conn, self._ctx, self)
        self.refresh()
