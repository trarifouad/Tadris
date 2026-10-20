from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QTabWidget, QVBoxLayout, QWidget

from tadris.core.context import UserContext
from tadris.core.dates import display_date
from tadris.i18n.fr import t
from tadris.services import auth
from tadris.ui.pages.setup_tabs import CatalogTab, HolidaysTab, RoomsTab, SchoolTab, YearsTab
from tadris.ui.pages.system_tabs import AboutTab
from tadris.ui.user_dialog import UserDialog
from tadris.ui.widgets.common import ask, primary_button, toast
from tadris.ui.widgets.tables import fill, item, ruled_table


class SettingsPage(QWidget):
    """Director-only settings: user accounts and the school structure."""

    def __init__(self, conn, ctx: UserContext):
        super().__init__()
        self._conn = conn
        self._ctx = ctx
        self.setObjectName("page")

        heading = QLabel(t["nav.settings"])
        heading.setObjectName("pageTitle")

        self.school = SchoolTab(conn, ctx)
        self.users = UsersTab(conn, ctx)
        self.years = YearsTab(conn, ctx)
        self.levels = CatalogTab(conn, ctx, "level")
        self.subjects = CatalogTab(conn, ctx, "subject")
        self.rooms = RoomsTab(conn, ctx)
        self.holidays = HolidaysTab(conn, ctx)
        self.about = AboutTab(conn, ctx)
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        for tab, key in ((self.school, "school"), (self.users, "users"), (self.years, "years"),
                         (self.levels, "levels"), (self.subjects, "subjects"),
                         (self.rooms, "rooms"), (self.holidays, "holidays"),
                         (self.about, "about")):
            self.tabs.addTab(tab, t[f"settings.tab.{key}"])
        self.tabs.currentChanged.connect(self._refresh_tab)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 24)
        layout.setSpacing(16)
        layout.addWidget(heading)
        layout.addWidget(self.tabs, 1)

    # Kept for the users tab's callers and tests.
    @property
    def table(self):
        return self.users.table

    @property
    def new_user(self):
        return self.users.new_user

    def refresh(self) -> None:
        self.tabs.currentWidget().refresh()

    def _refresh_tab(self, index: int) -> None:
        # Counts (groups, slots) change elsewhere; reload when a tab comes into view.
        self.tabs.widget(index).refresh()


class UsersTab(QWidget):
    def __init__(self, conn, ctx: UserContext):
        super().__init__()
        self._conn = conn
        self._ctx = ctx

        section_caption = QLabel(t["users.caption"])
        section_caption.setObjectName("caption")
        self.new_user = primary_button(t["users.new"])
        self.new_user.setDefault(False)
        self.new_user.clicked.connect(self._create_user)
        section_head = QHBoxLayout()
        section_head.addWidget(section_caption)
        section_head.addStretch()
        section_head.addWidget(self.new_user, alignment=Qt.AlignmentFlag.AlignBottom)

        self.table = ruled_table([
            t["users.col.username"],
            t["users.col.role"],
            t["users.col.status"],
            t["users.col.created"],
        ])

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 16, 0, 0)
        layout.setSpacing(12)
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
        if not ask(dialog):
            return
        self.refresh()
        message = t["users.created"].format(username=dialog.username.text().strip())
        toast(self, message)
