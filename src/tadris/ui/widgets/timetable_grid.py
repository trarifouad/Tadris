from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from tadris.domain.models import Slot
from tadris.i18n.fr import t
from tadris.ui.theme import tokens
from tadris.ui.widgets.inputs import WEEK_ORDER

HEADER = 36
GUTTER = 56
HOUR_HEIGHT = 48
RADIUS = 10
DEFAULT_HOURS = ("08:00", "20:00")
SNAP_MINUTES = 15
EDGE = 3


def minutes(hhmm: str) -> int:
    hours, mins = hhmm.split(":")
    return int(hours) * 60 + int(mins)


class TimetableGrid(QWidget):
    """Week grid, Saturday to Friday, one block per slot.

    `detail` chooses the block's last line: "room" or "teacher". Clicking a block emits
    slot_clicked; double-clicking an empty spot emits empty_double_clicked(weekday, 'HH:MM').
    """

    slot_clicked = Signal(object)
    empty_double_clicked = Signal(int, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.slots: list[Slot] = []
        self.detail = "room"
        self.today_weekday: int | None = None
        self.first_hour, self.last_hour = self._hour_range(DEFAULT_HOURS, [])
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._resize_to_hours()

    # ----- data -----

    def set_slots(self, slots: list[Slot], detail: str = "room",
                  today_weekday: int | None = None,
                  hours: tuple[str, str] = DEFAULT_HOURS) -> None:
        """hours: the school's opening hours, the rows shown (widened for any older slot
        outside them)."""
        self.slots = slots
        self.detail = detail
        self.today_weekday = today_weekday
        self.first_hour, self.last_hour = self._hour_range(hours, slots)
        self._resize_to_hours()
        self.update()

    @staticmethod
    def _hour_range(hours: tuple[str, str], slots: list[Slot]) -> tuple[int, int]:
        starts = [minutes(hours[0]), *(minutes(s.start_time) for s in slots)]
        ends = [minutes(hours[1]), *(minutes(s.end_time) for s in slots)]
        return min(starts) // 60, -(-max(ends) // 60)  # whole hours, rounded outward

    def _resize_to_hours(self) -> None:
        self.setFixedHeight(HEADER + (self.last_hour - self.first_hour) * HOUR_HEIGHT + 1)

    def sizeHint(self) -> QSize:
        return QSize(900, self.height())

    # ----- geometry -----

    def _column_width(self) -> float:
        return (self.width() - GUTTER - 1) / len(WEEK_ORDER)

    def _y(self, minute: int) -> float:
        return HEADER + (minute - self.first_hour * 60) * HOUR_HEIGHT / 60

    def slot_rect(self, slot: Slot) -> QRectF:
        column = WEEK_ORDER.index(slot.weekday)
        width = self._column_width()
        top = self._y(minutes(slot.start_time))
        bottom = self._y(minutes(slot.end_time))
        return QRectF(GUTTER + column * width + 3, top + 1, width - 6, bottom - top - 2)

    def slot_at(self, point: QPointF) -> Slot | None:
        for slot in self.slots:
            if self.slot_rect(slot).contains(point):
                return slot
        return None

    def cell_at(self, point: QPointF) -> tuple[int, str] | None:
        """(weekday, time snapped down to a quarter hour) under a point of the grid."""
        if point.x() < GUTTER or point.y() < HEADER:
            return None
        column = int((point.x() - GUTTER) // self._column_width())
        if not 0 <= column < len(WEEK_ORDER):
            return None
        minute = self.first_hour * 60 + int((point.y() - HEADER) * 60 / HOUR_HEIGHT)
        minute -= minute % SNAP_MINUTES
        if minute >= self.last_hour * 60:
            return None
        return WEEK_ORDER[column], f"{minute // 60:02d}:{minute % 60:02d}"

    # ----- mouse -----

    def mouseMoveEvent(self, event):
        over = self.slot_at(event.position()) is not None
        self.setCursor(Qt.CursorShape.PointingHandCursor if over else Qt.CursorShape.ArrowCursor)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            slot = self.slot_at(event.position())
            if slot is not None:
                self.slot_clicked.emit(slot)
                return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.slot_at(event.position()) is None:
            cell = self.cell_at(event.position())
            if cell is not None:
                self.empty_double_clicked.emit(*cell)
                return
        super().mouseDoubleClickEvent(event)

    # ----- painting -----

    def paintEvent(self, event):
        theme = tokens()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        frame = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        outline = QPainterPath()
        outline.addRoundedRect(frame, RADIUS, RADIUS)
        painter.setClipPath(outline)  # the card's rounded corners
        painter.fillRect(self.rect(), QColor(theme["surface"]))
        width = self._column_width()
        if self.today_weekday is not None:
            column = WEEK_ORDER.index(self.today_weekday)
            painter.fillRect(QRectF(GUTTER + column * width, HEADER, width, self.height()),
                             QColor(theme["bg"]))
        self._paint_header(painter, theme, width)
        self._paint_hours(painter, theme, width)
        for slot in self.slots:
            self._paint_slot(painter, theme, slot)
        painter.setClipping(False)
        painter.setPen(QPen(QColor(theme["border"]), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(outline)
        painter.end()

    def _paint_header(self, painter, theme, width) -> None:
        painter.fillRect(QRectF(0, 0, self.width(), HEADER), QColor(theme["surface_alt"]))
        font = QFont(self.font())
        font.setPixelSize(12)
        font.setWeight(QFont.Weight.Medium)
        painter.setFont(font)
        for column, weekday in enumerate(WEEK_ORDER):
            today = weekday == self.today_weekday
            painter.setPen(QColor(theme["primary" if today else "muted"]))
            name = t[f"weekday.{weekday}"]
            rect = QRectF(GUTTER + column * width, 0, width, HEADER)
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, name[:1].upper() + name[1:])
        painter.setPen(QPen(QColor(theme["rule_strong"]), 1))
        painter.drawLine(QPointF(0, HEADER), QPointF(self.width(), HEADER))

    def _paint_hours(self, painter, theme, width) -> None:
        mono = QFont("IBM Plex Mono")
        mono.setPixelSize(11)
        painter.setFont(mono)
        for hour in range(self.first_hour, self.last_hour + 1):
            y = self._y(hour * 60)
            if hour > self.first_hour:
                painter.setPen(QPen(QColor(theme["rule"]), 1))
                painter.drawLine(QPointF(GUTTER, y), QPointF(self.width(), y))
            if hour < self.last_hour:
                painter.setPen(QColor(theme["faint"]))
                painter.drawText(QRectF(0, y + 2, GUTTER - 8, 16),
                                 Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop,
                                 f"{hour:02d}:00")
        painter.setPen(QPen(QColor(theme["border"]), 1))
        for column in range(len(WEEK_ORDER)):
            x = GUTTER + column * width
            painter.drawLine(QPointF(x, HEADER), QPointF(x, self.height()))

    def _paint_slot(self, painter, theme, slot: Slot) -> None:
        rect = self.slot_rect(slot)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(theme["primary_soft"]))
        painter.drawRoundedRect(rect, 6, 6)
        painter.setBrush(QColor(theme["primary"]))
        painter.drawRoundedRect(QRectF(rect.left(), rect.top(), EDGE + 3, rect.height()), 3, 3)
        painter.fillRect(QRectF(rect.left() + EDGE, rect.top(), 3, rect.height()),
                         QColor(theme["primary_soft"]))

        inner = rect.adjusted(EDGE + 7, 5, -6, -4)
        title = QFont(self.font())
        title.setPixelSize(12)
        title.setWeight(QFont.Weight.DemiBold)
        body = QFont(self.font())
        body.setPixelSize(11)
        last = slot.room if self.detail == "room" else (slot.teacher or "")
        lines = [
            (title, theme["text"], slot.group),
            (body, theme["muted"], f"{slot.subject} · {slot.level}"),
            (body, theme["muted"], f"{slot.start_time}–{slot.end_time} · {last}"),
        ]
        y = inner.top()
        painter.save()
        painter.setClipRect(inner)
        for font, color, text in lines:
            metrics = QFontMetrics(font)
            if y + metrics.height() > inner.bottom() + 2:
                break
            painter.setFont(font)
            painter.setPen(QColor(color))
            elided = metrics.elidedText(text, Qt.TextElideMode.ElideRight, int(inner.width()))
            painter.drawText(QRectF(inner.left(), y, inner.width(), metrics.height()),
                             Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, elided)
            y += metrics.height()
        painter.restore()
