from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
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
from tadris.ui.theme import icon
from tadris.ui.widgets.common import confirm

SIDEBAR_WIDTH = 216


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
        self._conn = conn
        self.ctx = ctx
        school = settings.get(conn, "school.name")
        self.setWindowTitle(f"{t['app.name']} · {school}" if school else t["app.name"])
        self.resize(1280, 800)

        self.pages = QStackedWidget()
        self.nav_buttons: dict[str, QPushButton] = {}
        self._slots: dict[str, int] = {}
        self._built: set[str] = set()
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)

        root = QWidget()
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._build_sidebar())
        layout.addWidget(self.pages, 1)
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
            return SettingsPage(self._conn, self.ctx)
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
        """Show another page from a link (the dashboard's « Voir tout »), if the user has it."""
        button = self.nav_buttons.get(key)
        if button is not None:
            button.click()

    def open_student(self, student_id: int) -> None:
        """Show a student's page from another page (e.g. a list of months to renew)."""
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
        brand.setContentsMargins(10, 0, 10, 16)
        brand.setSpacing(8)
        latin = QLabel("Tadris")
        latin.setObjectName("wordmark")
        arabic = QLabel("تدريس")
        arabic.setObjectName("wordmarkAr")
        brand.addWidget(latin)
        brand.addWidget(arabic)
        brand.addStretch()
        layout.addLayout(brand)

        for key, label_key in nav_for(self.ctx):
            label = t[label_key]
            # Pages are built on first visit: startup stays fast and each page loads fresh.
            self._slots[key] = self.pages.addWidget(QWidget())
            button = QPushButton(label)
            button.setObjectName("navItem")
            button.setCheckable(True)
            button.clicked.connect(lambda _checked, k=key, lb=label: self._show(k, lb))
            self._group.addButton(button)
            self.nav_buttons[key] = button
            layout.addWidget(button)

        layout.addStretch()

        footer = QFrame()
        footer.setObjectName("sidebarFooter")
        footer_layout = QVBoxLayout(footer)
        footer_layout.setContentsMargins(12, 12, 12, 0)
        footer_layout.setSpacing(0)
        user = QLabel(self.ctx.username)
        user.setObjectName("sidebarUser")
        role = QLabel(t[f"role.{self.ctx.role}"])
        role.setObjectName("sidebarRole")
        footer_layout.addWidget(user)
        footer_layout.addWidget(role)
        footer_layout.addSpacing(10)
        self.logout_button = QPushButton(t["main.logout"])
        self.logout_button.setObjectName("sidebarLogout")
        self.logout_button.setIcon(icon("log-out", "on_primary"))
        self.logout_button.setIconSize(QSize(16, 16))
        self.logout_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.logout_button.setToolTip(t["main.logout_tip"])
        self.logout_button.clicked.connect(self.logout)
        footer_layout.addWidget(self.logout_button)
        layout.addWidget(footer)
        return sidebar

    def has_unsaved(self) -> bool:
        return any(getattr(self.pages.widget(self._slots[key]), "has_unsaved", lambda: False)()
                   for key in self._built)

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
