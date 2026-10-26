"""Paramètres (director only): a short list of sections on the left, the chosen one on the
right. École (identity, opening hours, default prices, receipt lines), Structure (année
scolaire → niveaux → matières → salles, and the holidays), Utilisateurs, Données (backups,
about). Each section sums things up; « Modifier » or « Gérer » opens the details.
`restored`: a copy of the database was put back (the window goes back to the login
screen)."""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from tadris.core.context import UserContext
from tadris.i18n.fr import t
from tadris.ui.pages.settings.data import DataSection
from tadris.ui.pages.settings.school import SchoolSection
from tadris.ui.pages.settings.structure import StructureSection
from tadris.ui.pages.settings.users import UsersSection
from tadris.ui.widgets.side_nav import SideNav

SECTIONS = (("school", "building-2"), ("structure", "layers"), ("users", "users"),
            ("data", "database"))
# The tabs of the old page (links such as « settings/backups ») and where they are now.
OLD_TABS = {"backups": "data", "about": "data", "years": "structure", "levels": "structure",
            "subjects": "structure", "rooms": "structure", "holidays": "structure"}
CONTENT_WIDTH = 880  # the cards stop there on a wide screen


class SettingsPage(QWidget):
    restored = Signal(str)  # the safety copy taken before

    def __init__(self, conn, ctx: UserContext):
        super().__init__()
        self._conn = conn
        self._ctx = ctx
        self.setObjectName("page")

        heading = QLabel(t["nav.settings"])
        heading.setObjectName("pageTitle")
        self.sections = {"school": SchoolSection(conn, ctx),
                         "structure": StructureSection(conn, ctx),
                         "users": UsersSection(conn, ctx),
                         "data": DataSection(conn, ctx)}
        self.sections["data"].restored.connect(self.restored.emit)
        self.nav = SideNav([(key, t[f"settings.section.{key}"], icon_name)
                            for key, icon_name in SECTIONS])
        self.nav.changed.connect(self.show_section)
        self.stack = QStackedWidget()
        for key, _icon in SECTIONS:
            self.stack.addWidget(self._scrolled(self.sections[key]))

        body = QHBoxLayout()
        body.setSpacing(24)
        body.addWidget(self.nav)
        body.addWidget(self.stack, 1)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 24)
        layout.setSpacing(16)
        layout.addWidget(heading)
        layout.addLayout(body, 1)
        self.nav.select("school")

    @staticmethod
    def _scrolled(section: QWidget) -> QScrollArea:
        """A section scrolls on a small screen rather than squeeze its cards."""
        section.setMaximumWidth(CONTENT_WIDTH)
        box = QWidget()
        inner = QVBoxLayout(box)
        inner.setContentsMargins(0, 0, 0, 0)
        inner.addWidget(section)
        inner.addStretch()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(box)
        return scroll

    # Kept for the users list's callers and tests.
    @property
    def table(self):
        return self.sections["users"].table

    @property
    def new_user(self):
        return self.sections["users"].new_user

    def current_section(self) -> str:
        return self.nav.current()

    def show_section(self, key: str) -> None:
        """Show a section, read again: counts change on other pages."""
        self.nav.select(key)
        self.stack.setCurrentIndex([k for k, _icon in SECTIONS].index(key))
        self.sections[key].refresh()

    def show_tab(self, name: str) -> None:
        """A section by its name, or by the tab of the old page that held it (« backups »)."""
        key = OLD_TABS.get(name, name)
        if key in self.sections:
            self.show_section(key)

    def refresh(self) -> None:
        self.sections[self.current_section()].refresh()
