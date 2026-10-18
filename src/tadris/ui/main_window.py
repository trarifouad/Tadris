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
from tadris.services import settings
from tadris.ui.pages.settings import SettingsPage

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
    def __init__(self, conn, ctx: UserContext):
        super().__init__()
        self._conn = conn
        self.ctx = ctx
        school = settings.get(conn, "school.name")
        self.setWindowTitle(f"{t['app.name']} · {school}" if school else t["app.name"])
        self.resize(1280, 800)

        self.pages = QStackedWidget()
        self.nav_buttons: dict[str, QPushButton] = {}
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

    def _page_for(self, key: str, label: str) -> QWidget:
        if key == "settings":
            return SettingsPage(self._conn, self.ctx)
        return PlaceholderPage(label)

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
            index = self.pages.addWidget(self._page_for(key, label))
            button = QPushButton(label)
            button.setObjectName("navItem")
            button.setCheckable(True)
            button.clicked.connect(lambda _checked, i=index: self.pages.setCurrentIndex(i))
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
        layout.addWidget(footer)
        return sidebar
