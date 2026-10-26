"""A page's own short list of sections, on its left (Paramètres): one checked at a time, its
icon in the ink colour once checked."""

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QButtonGroup, QFrame, QPushButton, QVBoxLayout

from tadris.ui.theme import icon

WIDTH = 200


def _item_icon(name: str) -> QIcon:
    result = icon(name, "muted")
    result.addPixmap(icon(name, "primary").pixmap(40, 40), QIcon.Mode.Normal, QIcon.State.On)
    return result


class SideNav(QFrame):
    """items: (key, label, icon name). `changed(key)` when the user picks another one."""

    changed = Signal(str)

    def __init__(self, items: list[tuple[str, str, str]]):
        super().__init__()
        self.setObjectName("sideNav")
        self.setFixedWidth(WIDTH)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.buttons: dict[str, QPushButton] = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        for key, label, icon_name in items:
            button = QPushButton(label)
            button.setObjectName("sideNavItem")
            button.setCheckable(True)
            button.setAutoDefault(False)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setIcon(_item_icon(icon_name))
            button.setIconSize(QSize(18, 18))
            button.clicked.connect(lambda _on=False, k=key: self.changed.emit(k))
            self.group.addButton(button)
            self.buttons[key] = button
            layout.addWidget(button)
        layout.addStretch()

    def select(self, key: str) -> None:
        """Check `key` without telling `changed` (the page shows it itself)."""
        self.buttons[key].setChecked(True)

    def current(self) -> str:
        return next(key for key, button in self.buttons.items() if button.isChecked())
