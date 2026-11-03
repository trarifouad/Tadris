"""The charts above a report, drawn with QPainter in the dashboard's style: figures in the UI
font with tabular digits (quieter than a monospace), `border` grid lines, the violet at two
strengths.

BarsChart: a group of bars per label (a month), one per series (« Facturé » soft, « Encaissé »
full). One month is always picked: the one under the mouse (`hovered`, -1 when it leaves),
else the `pinned` one (the latest with figures), so the readout never stands empty. A month
with nothing in it has its name faint.

RatesBars: a column per group (its attendance), the lowest first: red under 75 %, amber
under 85 %, a soft green from there; picked like the months, for the readout."""

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QWidget

from tadris.core.percent import format_percent
from tadris.services.reports import LOW_RATE_BP
from tadris.ui.pages.dashboard import figure, nice_step
from tadris.ui.pages.dues_view import tabular
from tadris.ui.theme import blend, tokens

GOOD_RATE_BP = 8500  # from here a rate is green


def series_colors() -> list[QColor]:
    """The first series soft, the next one full."""
    tk = tokens()
    return [QColor(blend(tk["primary"], tk["surface"], 0.35)), QColor(tk["primary"])]


def rate_tone(value: int) -> str:
    return ("success" if value >= GOOD_RATE_BP
            else "warning" if value >= LOW_RATE_BP else "danger")


class BarsChart(QWidget):
    hovered = Signal(int)
    GUTTER = 56  # the scale's figures
    LABELS = 24  # the months' names
    BAR_MAX = 26

    def __init__(self):
        super().__init__()
        self.setMouseTracking(True)
        self.setMinimumHeight(190)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.labels: tuple[str, ...] = ()
        self.series: tuple[tuple[str, tuple[int, ...]], ...] = ()
        self.hover = -1
        self.pinned = -1  # picked while the mouse is elsewhere

    def set_data(self, labels, series, pinned: int = -1) -> None:
        self.labels, self.series, self.hover = tuple(labels), tuple(series), -1
        self.pinned = pinned
        self.update()

    def picked(self) -> int:
        return self.hover if self.hover >= 0 else self.pinned

    def _plot(self) -> QRectF:
        return QRectF(self.GUTTER, 10, max(self.width() - self.GUTTER, 1),
                      max(self.height() - 10 - self.LABELS, 1))

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

    def _empty(self, i: int) -> bool:
        return not any(values[i] for _name, values in self.series)

    def paintEvent(self, event) -> None:
        tk = tokens()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setFont(tabular(size=11))
        plot = self._plot()
        top_value = max((v for _name, values in self.series for v in values), default=0)
        step = nice_step(top_value)
        top = step * 2
        grid = QColor(tk["border"])
        for k in range(3):
            y = round(plot.bottom() - k * step / top * plot.height()) + 0.5
            painter.setPen(QPen(grid, 1, Qt.PenStyle.SolidLine if k == 0
                                else Qt.PenStyle.DotLine))
            painter.drawLine(plot.left(), y, plot.right(), y)
            painter.setPen(QColor(tk["muted"]))
            painter.drawText(QRectF(0, y - 8, self.GUTTER - 12, 16),
                             Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                             figure(k * step))
        if not self.labels or not self.series:
            return
        slot = plot.width() / len(self.labels)
        colors = series_colors()
        count = len(self.series)
        bar = min(slot * 0.72 / count, self.BAR_MAX)
        gap = 4
        width = bar * count + gap * (count - 1)
        picked = self.picked()
        painter.setFont(tabular(size=12))
        for i, text in enumerate(self.labels):
            middle = plot.left() + slot * (i + 0.5)
            if i == picked:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(blend(tk["primary_soft"], tk["surface"], 0.6)))
                painter.drawRoundedRect(QRectF(middle - slot / 2 + 4, plot.top(), slot - 8,
                                               plot.height()), 6, 6)
            for k, (_name, values) in enumerate(self.series):
                value = values[i]
                if value <= 0:
                    continue
                height = max(value / top * plot.height(), 2)
                x = middle - width / 2 + k * (bar + gap)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(colors[k % len(colors)])
                painter.drawRoundedRect(QRectF(x, plot.bottom() - height, bar, height), 3, 3)
            color = ("primary" if i == picked else "faint" if self._empty(i) else "muted")
            painter.setPen(QColor(tk[color]))
            painter.drawText(QRectF(middle - slot / 2, plot.bottom() + 4, slot,
                                    self.LABELS - 6), Qt.AlignmentFlag.AlignCenter, text)


def rate_color(value: int) -> QColor:
    """A group's bar: red under 75 %, amber under 85 %, from there a soft green."""
    tk = tokens()
    tone = rate_tone(value)
    return QColor(blend(tk[tone], tk["surface"], 0.55) if tone == "success" else tk[tone])


def short_name(title: str) -> tuple[str, str]:
    """A group's title under its bar, on two lines: « Maths 4AM G2 · Mathématiques 4AM »
    gives (« Maths », « 4AM G2 »): its name, the subject left out."""
    name = title.split(" · ")[0]
    first, _space, rest = name.partition(" ")
    return first, rest


class RatesBars(QWidget):
    """A column per group, the lowest first, LIMIT of them (the table has every group):
    its height the rate, its colour the band, the rate on top, the group's short name
    under it. The 75 % line dashed across. One group is always picked, the one under the
    mouse (`hovered`, -1 when it leaves) else the lowest, for the readout."""

    hovered = Signal(int)
    GUTTER = 44  # the scale's figures
    LABELS = 34  # the names, on two lines
    TOP = 18  # the rate over the highest bar
    BAR_MAX = 34
    LIMIT = 10

    def __init__(self):
        super().__init__()
        self.setMouseTracking(True)
        self.setMinimumHeight(220)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.labels: tuple[str, ...] = ()
        self.values: tuple[int, ...] = ()
        self.hover = -1

    def set_data(self, labels, values) -> None:
        """The lowest rate first; equal rates by name."""
        pairs = sorted(zip(labels, values, strict=True),
                       key=lambda pair: (pair[1], pair[0].casefold()))
        self.labels = tuple(label for label, _value in pairs)
        self.values = tuple(value for _label, value in pairs)
        self.hover = -1
        self.update()

    def shown(self) -> int:
        return min(len(self.labels), self.LIMIT)

    def picked(self) -> int:
        if self.hover >= 0:
            return self.hover
        return 0 if self.labels else -1

    def _plot(self) -> QRectF:
        return QRectF(self.GUTTER, self.TOP, max(self.width() - self.GUTTER, 1),
                      max(self.height() - self.TOP - self.LABELS, 1))

    def index_at(self, x: float) -> int:
        plot = self._plot()
        count = self.shown()
        if not count or not plot.left() <= x < plot.right():
            return -1
        return min(int((x - plot.left()) / (plot.width() / count)), count - 1)

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
        plot = self._plot()

        def y_of(rate: int) -> float:
            return plot.bottom() - rate / 10000 * plot.height()

        painter.setFont(tabular(size=11))
        for rate in (0, 5000, 10000):
            y = round(y_of(rate)) + 0.5
            painter.setPen(QPen(QColor(tk["border"]), 1, Qt.PenStyle.SolidLine if rate == 0
                                else Qt.PenStyle.DotLine))
            painter.drawLine(plot.left(), y, plot.right(), y)
            painter.setPen(QColor(tk["muted"]))
            painter.drawText(QRectF(0, y - 8, self.GUTTER - 10, 16),
                             Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                             format_percent(rate))
        count = self.shown()
        if not count:
            return
        slot = plot.width() / count
        bar = min(slot * 0.56, self.BAR_MAX)
        picked = self.picked()
        for i in range(count):
            value, middle = self.values[i], plot.left() + slot * (i + 0.5)
            if i == picked:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(blend(tk["primary_soft"], tk["surface"], 0.6)))
                painter.drawRoundedRect(QRectF(middle - slot / 2 + 3, plot.top() - self.TOP,
                                               slot - 6, plot.height() + self.TOP), 6, 6)
            top = y_of(value)
            height = max(plot.bottom() - top, 2)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(rate_color(value))
            painter.drawRoundedRect(QRectF(middle - bar / 2, plot.bottom() - height, bar,
                                           height), 3, 3)
            tone = rate_tone(value)
            painter.setFont(tabular(size=11))
            painter.setPen(QColor(tk["muted"] if tone == "success" else tk[tone]))
            painter.drawText(QRectF(middle - slot / 2, plot.bottom() - height - 16, slot, 14),
                             Qt.AlignmentFlag.AlignCenter, format_percent(value))
            first, rest = short_name(self.labels[i])
            name_font = QFont(self.font())
            name_font.setPixelSize(11)
            painter.setFont(name_font)
            painter.setPen(QColor(tk["primary"] if i == picked else tk["muted"]))
            metrics = QFontMetrics(name_font)
            for line, text in enumerate((first, rest)):
                painter.drawText(QRectF(middle - slot / 2, plot.bottom() + 4 + line * 14,
                                        slot, 14), Qt.AlignmentFlag.AlignCenter,
                                 metrics.elidedText(text, Qt.TextElideMode.ElideRight,
                                                    int(slot) - 2))
        # Where a group turns red: the 75 % line, dashed, its figure in the scale.
        y = round(y_of(LOW_RATE_BP)) + 0.5
        pen = QPen(QColor(tk["danger"]), 1, Qt.PenStyle.CustomDashLine)
        pen.setDashPattern([3, 3])
        painter.setPen(pen)
        painter.setOpacity(0.55)
        painter.drawLine(plot.left(), y, plot.right(), y)
        painter.setOpacity(1)
        painter.setFont(tabular(size=11))
        painter.setPen(QColor(tk["danger"]))
        painter.drawText(QRectF(0, y - 8, self.GUTTER - 10, 16),
                         Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                         format_percent(LOW_RATE_BP))
