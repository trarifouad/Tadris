"""The charts above a report, drawn with QPainter in the dashboard's style: Plex Mono figures,
`border` grid lines, the violet at two strengths.

BarsChart: a group of bars per label (a month), one per series (« Facturé » soft, « Encaissé »
full); the mouse picks a label (`hovered`, -1 when it leaves). RatesChart: one horizontal bar
per label (a group's attendance), green, amber under 85 %, red under 75 %."""

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QWidget

from tadris.core.percent import format_percent
from tadris.services.reports import LOW_RATE_BP
from tadris.ui.pages.dashboard import figure, nice_step
from tadris.ui.theme import blend, tokens

GOOD_RATE_BP = 8500  # from here a rate is green


def _mono(size: int = 11) -> QFont:
    font = QFont("IBM Plex Mono")
    font.setPixelSize(size)
    return font


def series_colors() -> list[QColor]:
    """The first series soft, the next one full."""
    tk = tokens()
    return [QColor(blend(tk["primary"], tk["surface"], 0.35)), QColor(tk["primary"])]


class BarsChart(QWidget):
    hovered = Signal(int)
    GUTTER = 56  # the scale's figures
    LABELS = 22  # the months' names

    def __init__(self):
        super().__init__()
        self.setMouseTracking(True)
        self.setMinimumHeight(200)
        self.labels: tuple[str, ...] = ()
        self.series: tuple[tuple[str, tuple[int, ...]], ...] = ()
        self.hover = -1

    def set_data(self, labels, series) -> None:
        self.labels, self.series, self.hover = tuple(labels), tuple(series), -1
        self.update()

    def _plot(self) -> QRectF:
        return QRectF(self.GUTTER, 8, max(self.width() - self.GUTTER, 1),
                      max(self.height() - 8 - self.LABELS, 1))

    def index_at(self, x: float) -> int:
        plot = self._plot()
        if not self.labels or not plot.left() <= x < plot.right():
            return -1
        return min(int((x - plot.left()) / (plot.width() / len(self.labels))),
                   len(self.labels) - 1)

    def mouseMoveEvent(self, event) -> None:
        index = self.index_at(event.position().x())
        if index != self.hover:
            self.hover = index
            self.hovered.emit(index)
            self.update()

    def leaveEvent(self, event) -> None:
        super().leaveEvent(event)
        if self.hover != -1:
            self.hover = -1
            self.hovered.emit(-1)
            self.update()

    def paintEvent(self, event) -> None:
        tk = tokens()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setFont(_mono())
        plot = self._plot()
        top_value = max((v for _name, values in self.series for v in values), default=0)
        step = nice_step(top_value)
        top = step * 2
        for k in range(3):
            y = plot.bottom() - k * step / top * plot.height()
            painter.setPen(QPen(QColor(tk["border"]), 1))
            painter.drawLine(plot.left(), y, plot.right(), y)
            painter.setPen(QColor(tk["muted"]))
            painter.drawText(QRectF(0, y - 8, self.GUTTER - 10, 16),
                             Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                             figure(k * step))
        if not self.labels or not self.series:
            return
        slot = plot.width() / len(self.labels)
        colors = series_colors()
        count = len(self.series)
        bar = min(slot * 0.7 / count, 22)
        gap = 3
        width = bar * count + gap * (count - 1)
        for i, text in enumerate(self.labels):
            middle = plot.left() + slot * (i + 0.5)
            picked = i == self.hover
            if picked:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(tk["surface_alt"]))
                painter.drawRoundedRect(QRectF(middle - slot / 2 + 2, plot.top(), slot - 4,
                                               plot.height()), 6, 6)
            for k, (_name, values) in enumerate(self.series):
                value = values[i]
                if value <= 0:
                    continue
                height = max(value / top * plot.height(), 2)
                x = middle - width / 2 + k * (bar + gap)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(colors[k % len(colors)])
                painter.drawRoundedRect(QRectF(x, plot.bottom() - height, bar, height), 2, 2)
            painter.setPen(QColor(tk["text"] if picked else tk["muted"]))
            painter.drawText(QRectF(middle - slot / 2, plot.bottom() + 4, slot,
                                    self.LABELS - 4), Qt.AlignmentFlag.AlignCenter, text)


class RatesChart(QWidget):
    ROW = 26  # a group's bar and its gap
    VALUE = 64  # the rate, at the end of the bar

    def __init__(self):
        super().__init__()
        self.labels: tuple[str, ...] = ()
        self.values: tuple[int, ...] = ()

    def set_data(self, labels, values) -> None:
        self.labels, self.values = tuple(labels), tuple(values)
        self.setFixedHeight(max(len(self.labels), 1) * self.ROW + 8)
        self.update()

    def _name_width(self) -> int:
        metrics = QFontMetrics(self.font())
        widest = max((metrics.horizontalAdvance(text) for text in self.labels), default=0)
        return min(widest + 16, max(self.width() // 3, 120))

    def paintEvent(self, event) -> None:
        tk = tokens()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        names = self._name_width()
        track = max(self.width() - names - self.VALUE, 1)
        metrics = QFontMetrics(self.font())
        for i, (text, value) in enumerate(zip(self.labels, self.values, strict=True)):
            top = 4 + i * self.ROW
            painter.setFont(self.font())
            painter.setPen(QColor(tk["text"]))
            painter.drawText(QRectF(0, top, names - 12, self.ROW - 6),
                             Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                             metrics.elidedText(text, Qt.TextElideMode.ElideRight, names - 12))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(tk["surface_alt"]))
            painter.drawRoundedRect(QRectF(names, top + 5, track, self.ROW - 16), 4, 4)
            tone = ("success" if value >= GOOD_RATE_BP
                    else "warning" if value >= LOW_RATE_BP else "danger")
            painter.setBrush(QColor(tk[tone]))
            painter.drawRoundedRect(QRectF(names, top + 5, max(track * value / 10000, 3),
                                           self.ROW - 16), 4, 4)
            painter.setFont(_mono(12))
            painter.setPen(QColor(tk["text"]))
            painter.drawText(QRectF(names + track + 8, top, self.VALUE - 8, self.ROW - 6),
                             Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                             format_percent(value))
