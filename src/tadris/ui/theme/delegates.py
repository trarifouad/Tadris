from PySide6.QtGui import QColor, QPen
from PySide6.QtWidgets import QStyledItemDelegate


class RuledDelegate(QStyledItemDelegate):
    """Seyès rules: a fine line under each row, a stronger one under every fifth row.

    QSS cannot target every fifth row, so the delegate paints the lines.
    """

    def __init__(self, tokens: dict, parent=None):
        super().__init__(parent)
        self._rule = QColor(tokens["rule"])
        self._strong = QColor(tokens["rule_strong"])

    def paint(self, painter, option, index):
        super().paint(painter, option, index)
        color = self._strong if (index.row() + 1) % 5 == 0 else self._rule
        painter.save()
        painter.setPen(QPen(color, 1))
        painter.drawLine(option.rect.bottomLeft(), option.rect.bottomRight())
        painter.restore()
