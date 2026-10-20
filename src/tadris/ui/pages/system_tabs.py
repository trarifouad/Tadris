"""Paramètres tabs about the app itself: « À propos » (versions, where the data lives)."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from tadris.core.context import UserContext
from tadris.i18n.fr import t
from tadris.services import about
from tadris.ui.widgets import common
from tadris.ui.widgets.forms import caption


def value_label() -> QLabel:
    """A value the user may select and copy (a path to read out on the phone)."""
    label = QLabel()
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    label.setWordWrap(True)
    return label


class AboutTab(QWidget):
    def __init__(self, conn, ctx: UserContext):
        super().__init__()
        self._conn = conn
        self._ctx = ctx
        intro = caption(t["about.caption"])
        intro.setWordWrap(True)
        self.app_version = value_label()
        self.schema_version = value_label()
        self.database = value_label()
        grid = QGridLayout()
        grid.setHorizontalSpacing(24)
        grid.setVerticalSpacing(10)
        for r, (label, value) in enumerate(((t["about.app_version"], self.app_version),
                                            (t["about.schema_version"], self.schema_version),
                                            (t["about.database"], self.database))):
            name = QLabel(label)
            name.setObjectName("fieldLabel")
            grid.addWidget(name, r, 0, Qt.AlignmentFlag.AlignTop)
            grid.addWidget(value, r, 1)
        grid.setColumnStretch(1, 1)
        self.open_folder = QPushButton(t["about.open_folder"])
        self.open_folder.setAutoDefault(False)
        self.open_folder.clicked.connect(self._open_folder)
        actions = QHBoxLayout()
        actions.addWidget(self.open_folder)
        actions.addStretch()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 16, 0, 0)
        layout.setSpacing(16)
        layout.addWidget(intro)
        layout.addLayout(grid)
        layout.addLayout(actions)
        layout.addStretch()
        self.refresh()

    def refresh(self) -> None:
        info = about.info(self._conn, self._ctx)
        self._info = info
        self.app_version.setText(info.app_version)
        self.schema_version.setText(str(info.schema_version))  # always the latest once open
        self.database.setText(str(info.database) if info.database else t["about.in_memory"])
        self.open_folder.setEnabled(info.database is not None)

    def _open_folder(self) -> None:
        if self._info.database is not None:
            common.open_folder(self._info.database.parent)
