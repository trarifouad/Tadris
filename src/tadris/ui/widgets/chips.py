"""A filter whose name sits inside its box: « Statut  Actifs ▾ », « Niveau  Tous ▾ ».

Two shapes: "pill" (Rapports, a rounded chip on the sheet) and "field" (a list page: the
box of an ordinary input, 6 px corners, 36 px high). The field inside is borderless; the box
shows the focus ring (QSS has no :focus-within) and turns violet once `active`, the filter
moved off what the page opened with."""

from PySide6.QtCore import QEvent, QObject, QSize
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QWidget

from tadris.ui.theme import icon


def repolish(widget: QWidget) -> None:
    widget.style().unpolish(widget)
    widget.style().polish(widget)


class Chip(QFrame):
    def __init__(self, text: str, field: QWidget, icon_name: str | None = None,
                 shape: str = "pill"):
        super().__init__()
        self.setObjectName("chip")
        self.setProperty("shape", shape)
        self.field = field
        line = QHBoxLayout(self)
        start = 12 if shape == "field" else 14
        line.setContentsMargins(start if text or icon_name else 6, 1, 6, 1)
        line.setSpacing(6)
        if icon_name:
            mark = QLabel()
            mark.setPixmap(icon(icon_name, "muted", 32).pixmap(QSize(15, 15)))
            line.addWidget(mark)
        if text:
            name = QLabel(text)
            name.setObjectName("chipLabel")
            name.setBuddy(field)
            line.addWidget(name)
        line.addWidget(field)
        _FocusRing(self, field)

    def set_active(self, active: bool) -> None:
        if self.property("active") != active:
            self.setProperty("active", active)
            repolish(self)
            for child in self.findChildren(QLabel):
                repolish(child)


class _FocusRing(QObject):
    """The chip shows its ring while its field has the keyboard."""

    def __init__(self, chip: Chip, field: QWidget):
        super().__init__(chip)
        self._chip = chip
        field.installEventFilter(self)

    def eventFilter(self, watched, event) -> bool:
        kind = event.type()
        if kind in (QEvent.Type.FocusIn, QEvent.Type.FocusOut):
            self._chip.setProperty("focused", kind == QEvent.Type.FocusIn)
            repolish(self._chip)
        return False
