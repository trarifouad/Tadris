"""Chips: short items placed left to right that wrap to a new line when the width runs out
(the levels, subjects and rooms of Paramètres → Structure)."""

from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtWidgets import QLayout, QWidget

from tadris.ui.widgets.common import Badge


class FlowLayout(QLayout):
    """Qt's flow layout: each item at its size hint, wrapping as a paragraph does."""

    def __init__(self, parent: QWidget | None = None, spacing: int = 6):
        super().__init__(parent)
        self._items = []
        self.setContentsMargins(0, 0, 0, 0)
        self.setSpacing(spacing)

    def addItem(self, item) -> None:
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int):
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int):
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._place(QRect(0, 0, width, 0), apply=False)

    def setGeometry(self, rect: QRect) -> None:
        super().setGeometry(rect)
        self._place(rect, apply=True)

    def sizeHint(self) -> QSize:
        return self.minimumSize()

    def minimumSize(self) -> QSize:
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        return size + QSize(margins.left() + margins.right(), margins.top() + margins.bottom())

    def _place(self, rect: QRect, apply: bool) -> int:
        """Lay the items out in `rect` (or only measure them); returns the height used."""
        margins = self.contentsMargins()
        area = rect.adjusted(margins.left(), margins.top(), -margins.right(), -margins.bottom())
        x, y, line = area.x(), area.y(), 0
        gap = self.spacing()
        for item in self._items:
            if item.isEmpty():  # a hidden widget takes no room
                continue
            hint = item.sizeHint()
            if x + hint.width() > area.right() + 1 and line > 0:
                x, y, line = area.x(), y + line + gap, 0
            if apply:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x += hint.width() + gap
            line = max(line, hint.height())
        return y + line - rect.y() + margins.bottom()


def chips_box() -> tuple[QWidget, FlowLayout]:
    box = QWidget()
    return box, FlowLayout(box)


def set_chips(layout: FlowLayout, chips: list[tuple[str, bool]]) -> None:
    """One chip per (text, in use); an item no longer in use reads faint."""
    while layout.count():
        widget = layout.takeAt(0).widget()
        if widget is not None:
            widget.setParent(None)  # gone from the box now, not at the next event loop
            widget.deleteLater()
    for text, in_use in chips:
        chip = Badge(text, "neutral")
        chip.setProperty("faint", not in_use)
        layout.addWidget(chip)
