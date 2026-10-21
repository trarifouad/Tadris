import re

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QFont, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from tadris.core.context import UserContext
from tadris.core.permissions import nav_for
from tadris.i18n.fr import t
from tadris.services import auth, settings
from tadris.ui.pages.attendance import AttendancePage
from tadris.ui.pages.dashboard import DashboardPage
from tadris.ui.pages.groups import GroupsPage
from tadris.ui.pages.payments_page import PaymentsPage
from tadris.ui.pages.payouts_page import PayoutsPage
from tadris.ui.pages.reports import ReportsPage
from tadris.ui.pages.settings import SettingsPage
from tadris.ui.pages.students import StudentsPage
from tadris.ui.pages.subscriptions_page import SubscriptionsPage
from tadris.ui.pages.teachers import TeachersPage
from tadris.ui.pages.timetable import TimetablePage
from tadris.ui.theme import nav_icon
from tadris.ui.widgets.common import confirm, variant_button

SIDEBAR_WIDTH = 216
NAV_ICONS = {
    "dashboard": "house", "students": "users", "groups": "layers", "timetable": "calendar",
    "attendance": "square-check", "subscriptions": "arrow-right-left", "payments": "wallet",
    "payouts": "banknote", "reports": "chart-column", "teachers": "graduation-cap",
    "sms": "message-square", "settings": "sliders-vertical",
}
# Headed sidebar sections; the items above the first heading are the day's work.
NAV_SECTIONS = {
    "nav.section.money": ("subscriptions", "payments", "payouts", "reports"),
    "nav.section.school": ("teachers", "sms", "settings"),
}
SECTION_OF = {key: section for section, keys in NAV_SECTIONS.items() for key in keys}


def initials(username: str) -> str:
    """Two letters for the avatar: the first of two words (« fouad.trari » → FT), else the
    first two of the name."""
    words = re.split(r"[\s._-]+", username.strip())
    if len(words) >= 2:
        return (words[0][0] + words[1][0]).upper()
    return username[:2].upper()


class PlaceholderPage(QWidget):
    """Page shell until the phase that builds it."""

    def __init__(self, title: str):
        super().__init__()
        self.setObjectName("page")
        heading = QLabel(title)
        heading.setObjectName("pageTitle")
        caption = QLabel(t["page.placeholder"])
        caption.setObjectName("caption")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 24)
        layout.setSpacing(4)
        layout.addWidget(heading)
        layout.addWidget(caption)
        layout.addStretch()


class MainWindow(QMainWindow):
    logged_out = Signal()

    def __init__(self, conn, ctx: UserContext):
        super().__init__()
        self.logging_out = False  # closed by « Se déconnecter », not to quit the app
        self.restored = False  # a copy of the database was put back: log in again
        self._conn = conn
        self.ctx = ctx
        school = settings.get(conn, "school.name")
        self.setWindowTitle(f"{t['app.name']} · {school}" if school else t["app.name"])
        self.resize(1280, 800)

        self.pages = QStackedWidget()
        self.nav_buttons: dict[str, QPushButton] = {}
        self._labels: dict[str, str] = {}
        # Pages opened from another page (« Voir tout », a student double-clicked) can go
        # back to it: « ← Retour : Aujourd'hui » or Alt+←. A click in the sidebar
        # starts afresh. (No application-wide event filter for the mouse's back button: it
        # received objects being deleted and crashed PySide6.)
        self._current: str | None = None
        self._history: list[str] = []
        self._move = "sidebar"  # how the next page is reached: sidebar, link or back
        self.back_button = variant_button("", "ghost")
        self.back_button.setObjectName("backLink")
        self.back_button.clicked.connect(self.back)
        self.back_bar = QWidget()
        self.back_bar.setObjectName("page")
        bar = QHBoxLayout(self.back_bar)
        bar.setContentsMargins(16, 8, 24, 0)
        bar.addWidget(self.back_button)
        bar.addStretch()
        self.back_bar.hide()
        QShortcut(QKeySequence(QKeySequence.StandardKey.Back), self, self.back)
        self._slots: dict[str, int] = {}
        self._built: set[str] = set()
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)

        root = QWidget()
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._build_sidebar())
        main = QVBoxLayout()
        main.setContentsMargins(0, 0, 0, 0)
        main.setSpacing(0)
        main.addWidget(self.back_bar)
        main.addWidget(self.pages, 1)
        layout.addLayout(main, 1)
        self.setCentralWidget(root)

        role = t[f"role.{ctx.role}"]
        status = QLabel(t["main.user_status"].format(username=ctx.username, role=role))
        self.statusBar().addWidget(status)
        self.statusBar().setSizeGripEnabled(False)

        first = next(iter(self.nav_buttons.values()), None)
        if first is not None:
            first.click()

    def _show(self, key: str, label: str) -> None:
        index = self._slots[key]
        if key not in self._built:
            placeholder = self.pages.widget(index)
            self.pages.removeWidget(placeholder)
            placeholder.deleteLater()
            self.pages.insertWidget(index, self._page_for(key, label))
            self._built.add(key)
        else:
            # Other pages (or the other workstation) may have changed what it shows.
            page = self.pages.widget(index)
            if hasattr(page, "refresh"):
                page.refresh()
        self.pages.setCurrentIndex(index)
        self._arrived(key)

    def _arrived(self, key: str) -> None:
        previous, move = self._current, self._move
        self._move = "sidebar"
        if move == "link":
            if previous is not None and previous != key:
                self._history.append(previous)
        elif move == "sidebar":
            self._history.clear()
        self._current = key
        if self._history:
            self.back_button.setText(t["main.back"].format(page=self._labels[self._history[-1]]))
        self.back_bar.setVisible(bool(self._history))

    def back(self) -> None:
        """The page this one was opened from."""
        if not self._history:
            return
        self._move = "back"
        self.nav_buttons[self._history.pop()].click()

    def _page_for(self, key: str, label: str) -> QWidget:
        pages = {
            "students": StudentsPage,
            "groups": GroupsPage,
            "timetable": TimetablePage,
            "teachers": TeachersPage,
            "attendance": AttendancePage,
            "payouts": PayoutsPage,
        }
        if key in pages:
            return pages[key](self._conn, self.ctx)
        if key == "settings":
            page = SettingsPage(self._conn, self.ctx)
            page.restored.connect(self._restored)
            return page
        student_pages = {"subscriptions": SubscriptionsPage, "payments": PaymentsPage,
                         "reports": ReportsPage, "dashboard": DashboardPage}
        if key in student_pages:
            page = student_pages[key](self._conn, self.ctx)
            page.open_student.connect(self.open_student)
            if key == "dashboard":
                page.navigate.connect(self.go_to)
            return page
        return PlaceholderPage(label)

    def go_to(self, key: str) -> None:
        """Show another page from a link (the dashboard's « Voir tout »), if the user has it.
        « settings/backups » also opens that tab of the page."""
        key, _, tab = key.partition("/")
        button = self.nav_buttons.get(key)
        if button is not None:
            self._move = "link"
            button.click()
            page = self.pages.widget(self._slots[key])
            if tab and hasattr(page, "show_tab"):
                page.show_tab(tab)

    def open_student(self, student_id: int) -> None:
        """Show a student's page from another page (e.g. a list of months to renew)."""
        self._move = "link"
        self.nav_buttons["students"].click()
        self.pages.widget(self._slots["students"]).open_student(student_id)

    def _build_sidebar(self) -> QFrame:
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(SIDEBAR_WIDTH)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(10, 18, 10, 14)
        layout.setSpacing(2)

        brand = QHBoxLayout()
        brand.setContentsMargins(10, 0, 10, 12)
        brand.setSpacing(8)
        latin = QLabel("Tadris")
        latin.setObjectName("wordmark")
        arabic = QLabel("تدريس")
        arabic.setObjectName("wordmarkAr")
        brand.addWidget(latin)
        brand.addWidget(arabic)
        brand.addStretch()
        layout.addLayout(brand)

        # Role-based items are hidden, so a heading shows only above an item the user has.
        current = None
        for key, label_key in nav_for(self.ctx):
            section = SECTION_OF.get(key)
            if section != current and section is not None:
                layout.addWidget(self._section_heading(t[section]))
            current = section
            label = t[label_key]
            self._labels[key] = label
            # Pages are built on first visit: startup stays fast and each page loads fresh.
            self._slots[key] = self.pages.addWidget(QWidget())
            button = QPushButton(label)
            button.setObjectName("navItem")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            if key in NAV_ICONS:
                # Drawn 18 px with 5 px of room before the label (40 + 11 at 2.2×).
                button.setIcon(nav_icon(NAV_ICONS[key], gap=11))
                button.setIconSize(QSize(23, 18))
            button.clicked.connect(lambda _checked, k=key, lb=label: self._show(k, lb))
            self._group.addButton(button)
            self.nav_buttons[key] = button
            layout.addWidget(button)

        layout.addStretch()

        footer = QFrame()
        footer.setObjectName("sidebarFooter")
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(6, 10, 0, 0)
        footer_layout.setSpacing(10)
        avatar = QLabel(initials(self.ctx.username))
        avatar.setObjectName("sidebarAvatar")
        avatar.setFixedSize(30, 30)
        avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        who = QVBoxLayout()
        who.setContentsMargins(0, 0, 0, 0)
        who.setSpacing(0)
        user = QLabel(self.ctx.username)
        user.setObjectName("sidebarUser")
        role = QLabel(t[f"role.{self.ctx.role}"])
        role.setObjectName("sidebarRole")
        who.addWidget(user)
        who.addWidget(role)
        # An icon on its own: the label stays as the accessible name and the tooltip.
        self.logout_button = QPushButton()
        self.logout_button.setObjectName("sidebarLogout")
        self.logout_button.setAccessibleName(t["main.logout"])
        self.logout_button.setIcon(nav_icon("log-out"))
        self.logout_button.setIconSize(QSize(18, 18))
        self.logout_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.logout_button.setToolTip(f"{t['main.logout']}\n{t['main.logout_tip']}")
        self.logout_button.clicked.connect(self.logout)
        footer_layout.addWidget(avatar)
        footer_layout.addLayout(who, 1)
        footer_layout.addWidget(self.logout_button)
        layout.addWidget(footer)
        return sidebar

    @staticmethod
    def _section_heading(text: str) -> QLabel:
        heading = QLabel(text.upper())
        heading.setObjectName("navSection")
        font = heading.font()
        font.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 108)
        heading.setFont(font)
        return heading

    def has_unsaved(self) -> bool:
        return any(getattr(self.pages.widget(self._slots[key]), "has_unsaved", lambda: False)()
                   for key in self._built)

    def _restored(self, safety: str) -> None:
        """A copy of the database is in place: its accounts may differ, every page shows
        what is gone. Back to the login screen (nothing to ask: the restore was
        confirmed, and unsaved marks belonged to the data replaced)."""
        QMessageBox.information(self, t["restore.done_title"],
                                t["restore.done"].format(safety=safety))
        self.restored = True
        self.logging_out = True
        self.logged_out.emit()
        self.close()

    def logout(self) -> bool:
        """Back to the login screen. Unsaved attendance marks ask first. True if done."""
        if self.has_unsaved() and not confirm(self, t["attendance_view.leave_title"],
                                              t["attendance_view.leave"],
                                              t["main.logout"]):
            return False
        auth.logout(self._conn, self.ctx)
        self.logging_out = True
        self.logged_out.emit()
        self.close()
        return True
