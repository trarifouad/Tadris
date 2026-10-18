from PySide6.QtCore import QEvent, QRect, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QAbstractItemView, QStyle, QStyledItemDelegate, QStyleOptionViewItem

# Item data role holding a badge kind ("success", "neutral", ...) for BadgeDelegate.
KIND_ROLE = Qt.ItemDataRole.UserRole + 10
EDGE_WIDTH = 3
# Qt paints these per cell, which shows squares; the delegate paints them per row instead.
_ROW_STATES = (QStyle.StateFlag.State_Selected | QStyle.StateFlag.State_MouseOver
               | QStyle.StateFlag.State_HasFocus)


def blend(a: str, b: str, amount: float) -> QColor:
    """Mix two hex colors: amount 0 gives a, 1 gives b."""
    ca, cb = QColor(a), QColor(b)
    return QColor(*(round(x + (y - x) * amount) for x, y in (
        (ca.red(), cb.red()), (ca.green(), cb.green()), (ca.blue(), cb.blue())
    )))


class RuledDelegate(QStyledItemDelegate):
    """Table rows in the Encre style.

    - Seyès rules: a fine line under each row, a stronger one under every fifth row
      (QSS cannot target every fifth row).
    - Hover and selection cover the whole row, never a single cell; the selected row has a
      3 px ink edge on its leading side; no focus box around the current cell.
    """

    def __init__(self, tokens: dict, parent=None):
        super().__init__(parent)
        self._tokens = tokens
        self._rule = QColor(tokens["rule"])
        self._strong = QColor(tokens["rule_strong"])
        # Lighter than the selection, so a hovered row never reads as selected.
        self._hover = blend(tokens["surface"], tokens["surface_alt"], 0.55)
        self.hover_row = -1
        self._view = parent if isinstance(parent, QAbstractItemView) else None
        if self._view is not None:
            self._view.setMouseTracking(True)
            self._view.viewport().installEventFilter(self)

    def eventFilter(self, watched, event):
        kind = event.type()
        if kind == QEvent.Type.MouseMove:
            self._set_hover(self._view.indexAt(event.position().toPoint()).row())
        elif kind in (QEvent.Type.Leave, QEvent.Type.Hide):
            self._set_hover(-1)
        return False

    def _set_hover(self, row: int) -> None:
        if row == self.hover_row:
            return
        previous, self.hover_row = self.hover_row, row
        viewport = self._view.viewport()
        for r in (previous, row):
            if r >= 0:
                top = self._view.rowViewportPosition(r)
                viewport.update(QRect(0, top, viewport.width(), self._view.rowHeight(r)))

    def paint(self, painter, option, index):
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        self.paint_row_background(painter, option, index, selected)
        content = QStyleOptionViewItem(option)
        content.state &= ~_ROW_STATES
        self.paint_content(painter, content, index)
        self.paint_rule(painter, option, index)
        if selected and self._is_leading_column(index):
            painter.fillRect(
                QRect(option.rect.left(), option.rect.top(), EDGE_WIDTH, option.rect.height()),
                QColor(self._tokens["primary"]),
            )

    def paint_row_background(self, painter, option, index, selected: bool) -> None:
        if selected:
            painter.fillRect(option.rect, QColor(self._tokens["primary_soft"]))
        elif index.row() == self.hover_row:
            painter.fillRect(option.rect, self._hover)

    def paint_content(self, painter, option, index) -> None:
        super().paint(painter, option, index)

    def paint_rule(self, painter, option, index):
        color = self._strong if (index.row() + 1) % 5 == 0 else self._rule
        painter.save()
        painter.setPen(QPen(color, 1))
        painter.drawLine(option.rect.bottomLeft(), option.rect.bottomRight())
        painter.restore()

    def _is_leading_column(self, index) -> bool:
        if self._view is None or not hasattr(self._view, "horizontalHeader"):
            return index.column() == 0
        return self._view.horizontalHeader().visualIndex(index.column()) == 0


class BadgeDelegate(RuledDelegate):
    """Paints a cell's text as a status pill when the item carries a KIND_ROLE."""

    def paint_content(self, painter, option, index) -> None:
        kind = index.data(KIND_ROLE)
        if not kind:
            super().paint_content(painter, option, index)
            return
        text = index.data(Qt.ItemDataRole.DisplayRole) or ""
        font = QFont(option.font)
        font.setPixelSize(12)
        font.setWeight(QFont.Weight.Medium)
        metrics = QFontMetrics(font)
        width = metrics.horizontalAdvance(text) + 16
        height = metrics.height() + 4
        rect = QRect(option.rect.left() + 12, option.rect.center().y() - height // 2 + 1,
                     width, height)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(self._tokens[f"{kind}_bg"]))
        painter.drawRoundedRect(rect, 4, 4)
        painter.setPen(QColor(self._tokens[kind]))
        painter.setFont(font)
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)
        painter.restore()
