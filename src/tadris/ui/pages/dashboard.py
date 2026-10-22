"""Tableau de bord: the day at a glance.

A greeting with the date and one line on what needs doing. On the left, the money received
each day of the month (the director only) and the largest debts, each with « Encaisser »; on
the right, today's sessions, the groups with the most free
seats and, for the director, today's backup. A double-click on a debtor opens their page; each
card's link opens the page that handles the whole list.

It is read at a glance, so the page never scrolls: each list shows as many rows as the window
leaves room for (the lists of a column share it)."""

import html
import math
from collections.abc import Callable
from datetime import date

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from tadris.core.context import UserContext
from tadris.core.errors import BusinessRuleError
from tadris.core.money import format_dzd
from tadris.core.permissions import allowed
from tadris.domain.models import Dashboard, DashboardSession, DayCash, Debtor, GroupFill
from tadris.i18n.fr import t
from tadris.services import payments, printing, reports, students
from tadris.ui.payment_dialogs import PaymentDialog
from tadris.ui.student_dialog import StudentDialog
from tadris.ui.student_picker import StudentPicker
from tadris.ui.theme import blend, icon, tokens
from tadris.ui.widgets import common
from tadris.ui.widgets.common import Badge, ask, primary_button, toast
from tadris.ui.widgets.forms import caption

TOPBAR_HEIGHT = 56
ROW_HEIGHT = 40  # a debtor, a group
SESSION_ROW_HEIGHT = 56  # a session: two lines
SPACING = 16
PAD = 20  # a card's side padding
MIN_ROWS = 1  # a list with rows always shows at least this many
CONTENT_MAX = 1280  # wider windows leave the rest empty: lines stay short enough to read
OWED_WIDTH = 104
SINCE_WIDTH = 92
ACTION_WIDTH = 176
LATE_DAYS = 14  # « Depuis » turns amber from two weeks


# ----- text -----

def plural(key: str, count: int, **values) -> str:
    """`key`_0, _1 or _n, whichever fits count (_0 falls back to _n)."""
    if count == 0 and f"{key}_0" in t:
        suffix = "0"
    else:
        suffix = "1" if count == 1 else "n"
    return t[f"{key}_{suffix}"].format(count=count, **values)


def capitalized(text: str) -> str:
    return text[:1].upper() + text[1:]


def figure(amount: int) -> str:
    """An amount without « DA »: the chart's scale."""
    return format_dzd(amount).removesuffix(" DA")


def long_date(iso: str) -> str:
    """« Mercredi 21 octobre 2026 »."""
    day = date.fromisoformat(iso)
    return t["dashboard.long_date"].format(
        weekday=capitalized(t[f"weekday.{day.isoweekday()}"]), day=day.day,
        month=t[f"month.{day.month}"].lower(), year=day.year)


def short_date(iso: str) -> str:
    """« ven. 2 oct. »."""
    day = date.fromisoformat(iso)
    return f"{t[f'day_short.{day.isoweekday()}']} {day.day} {t[f'month_short.{day.month}']}"


def greeting(username: str, now: str) -> str:
    key = "dashboard.evening" if now >= "18:00" else "dashboard.hello"
    return t[key].format(name=capitalized(username))


def days_text(days: int) -> str:
    return t["dashboard.days_1"] if days == 1 else t["dashboard.days_n"].format(days=days)


def nice_step(top: int) -> int:
    """The chart's grid step: two steps reach `top`, each a round figure (1, 2, 2.5 or 5
    times a power of ten)."""
    half = max(top, 1) / 2
    power = 10 ** math.floor(math.log10(half))
    for mantissa in (1, 2, 2.5, 5, 10):
        if mantissa * power >= half:
            return max(math.ceil(mantissa * power), 1)
    return math.ceil(half)


def minutes(hhmm: str) -> int:
    hours, mins = hhmm.split(":")
    return int(hours) * 60 + int(mins)


def share_rows(room: int, counts: list[int], heights: list[int]) -> list[int]:
    """Split `room` pixels between lists of `counts` rows, each row `heights` tall: one row
    each in turn, so the lists show as many rows as one another, and what a short list does
    not need goes to the others. Every list with rows gets MIN_ROWS, even past the room."""
    shown = [0] * len(counts)
    added = True
    while added:
        added = False
        for i, (count, height) in enumerate(zip(counts, heights, strict=True)):
            if shown[i] < count and height <= room:
                shown[i] += 1
                room -= height
                added = True
    return [max(rows, min(count, MIN_ROWS)) for rows, count in zip(shown, counts, strict=True)]


# ----- small pieces -----

def link(text: str = "") -> QPushButton:
    button = QPushButton(text)
    button.setObjectName("link")
    button.setAutoDefault(False)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    return button


def label(text: str, name: str, align=None) -> QLabel:
    widget = QLabel(text)
    widget.setObjectName(name)
    if align is not None:
        widget.setAlignment(align | Qt.AlignmentFlag.AlignVCenter)
    return widget


def fixed(widget: QWidget, width: int, align=Qt.AlignmentFlag.AlignLeft) -> QWidget:
    """`widget` at the start (or end) of a box `width` wide: a column that lines up from row
    to row, whatever the widget's own width."""
    box = QWidget()
    box.setFixedWidth(width)
    layout = QHBoxLayout(box)
    layout.setContentsMargins(0, 0, 0, 0)
    if align == Qt.AlignmentFlag.AlignRight:
        layout.addStretch()
    layout.addWidget(widget, 0, Qt.AlignmentFlag.AlignVCenter)
    if align != Qt.AlignmentFlag.AlignRight:
        layout.addStretch()
    return box


class ElidedLabel(QLabel):
    """One line that ends in « … » when the column is too narrow, instead of setting the
    page's minimum width; struck through for a cancelled session."""

    def __init__(self, text: str, name: str, struck: bool = False):
        super().__init__(text)
        self.setObjectName(name)
        self.setProperty("struck", struck)
        self.setToolTip(text)
        self._struck = struck

    def minimumSizeHint(self) -> QSize:
        return QSize(24, super().minimumSizeHint().height())

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        font = self.font()
        font.setStrikeOut(self._struck)
        painter.setFont(font)
        painter.setPen(self.palette().color(self.foregroundRole()))
        rect = self.contentsRect()
        painter.drawText(rect, int(self.alignment()), QFontMetrics(font).elidedText(
            self.text(), Qt.TextElideMode.ElideRight, rect.width()))


class Card(QFrame):
    """A titled card: the title (a caption under it) on the left, a link or control on the
    right, then its body, edge to edge."""

    def __init__(self, title: str):
        super().__init__()
        self.setObjectName("card")
        self.title = label(title, "sectionTitle")
        self.subtitle = caption()
        self.subtitle.setTextFormat(Qt.TextFormat.RichText)
        self.subtitle.hide()
        names = QVBoxLayout()
        names.setSpacing(0)
        names.addWidget(self.title)
        names.addWidget(self.subtitle)
        self.side = QHBoxLayout()
        self.side.setSpacing(8)
        head = QHBoxLayout()
        head.setContentsMargins(PAD, 16, PAD, 12)
        head.addLayout(names, 1)
        head.addLayout(self.side)
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(0, 0, 0, 0)
        self.body.setSpacing(0)
        self.body.addLayout(head)

    def set_subtitle(self, text: str) -> None:
        self.subtitle.setText(text)
        self.subtitle.setVisible(bool(text))


def foot(*widgets, link_button: QPushButton | None = None) -> QFrame:
    """A card's bottom line: captions on the left, its link on the right."""
    frame = QFrame()
    frame.setObjectName("cardFoot")
    layout = QHBoxLayout(frame)
    layout.setContentsMargins(PAD, 12, PAD, 14)
    layout.setSpacing(6)
    for widget in widgets:
        if widget is None:
            layout.addSpacing(18)
        else:
            layout.addWidget(widget)
    layout.addStretch()
    if link_button is not None:
        layout.addWidget(link_button)
    return frame


class Row(QFrame):
    """One line of a list, a fixed height, ruled underneath; double-click runs `opened`."""

    def __init__(self, height: int, opened: Callable[[], None] | None = None):
        super().__init__()
        self.setObjectName("dashRow")
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)
        self.setFixedHeight(height)
        self._opened = opened
        self.line = QHBoxLayout(self)
        self.line.setContentsMargins(PAD, 0, PAD, 0)
        self.line.setSpacing(12)

    def mouseDoubleClickEvent(self, event) -> None:
        if self._opened is None:
            super().mouseDoubleClickEvent(event)
        else:
            self._opened()


class Rows(QWidget):
    """The rows of a list. Its minimum is one row, not all of them: a window made smaller
    can then shrink, and the page takes rows away (fit_rows()) instead of being held up."""

    def __init__(self):
        super().__init__()
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)

    def set(self, rows: list[QWidget]) -> None:
        while self._layout.count():
            old = self._layout.takeAt(0).widget()
            old.hide()
            old.setParent(None)
            old.deleteLater()
        for row in rows:
            self._layout.addWidget(row)
        self.setMinimumHeight(rows[0].height() * MIN_ROWS if rows else 0)

    def count(self) -> int:
        return self._layout.count()


class ListCard(Card):
    """A card whose rows are as many as the page gives it (show_rows())."""

    def __init__(self, title: str, empty: str, row_height: int):
        super().__init__(title)
        self.row_height = row_height
        self.rows = Rows()
        self.empty = caption(empty)
        self.empty.setContentsMargins(PAD, 0, PAD, 16)
        self._makers: list[Callable[[], QWidget]] = []
        self.shown = 0

    def place_rows(self) -> None:
        self.body.addWidget(self.rows)
        self.body.addWidget(self.empty)

    @property
    def count(self) -> int:
        return len(self._makers)

    def set_items(self, makers: list[Callable[[], QWidget]]) -> None:
        """One function per row that makes it: rows are made anew each time the list is
        drawn. Shows them all until the page says how many fit."""
        self._makers = makers
        self.empty.setVisible(not makers)
        self.shown = -1
        # One row until the page says how many fit: all of them would make the window grow.
        self.show_rows(MIN_ROWS)

    def show_rows(self, rows: int) -> None:
        rows = min(rows, len(self._makers))
        if rows == self.shown:
            return  # a resize that changes nothing here: the rows are not rebuilt
        self.shown = rows
        self.rows.set([make() for make in self._makers[:rows]])
        self.rows_shown()

    def rows_shown(self) -> None:
        """What changes with the number of rows shown (a footer's count)."""

    def frame_height(self) -> int:
        """The card's height without its rows: its border and every other part shown."""
        height = 2
        for i in range(self.body.count()):
            item = self.body.itemAt(i)
            widget = item.widget()
            if widget is self.rows or (widget is not None and widget.isHidden()):
                continue
            height += item.sizeHint().height()
        return height


# ----- the money of the month -----

class CashChart(QWidget):
    """A bar a day: what was received. A closed day is a stub on the axis; the dashed line is
    the average of the days open. The mouse picks a day (`hovered`, -1 when it leaves)."""

    hovered = Signal(int)
    GUTTER = 48  # the scale's figures
    LABELS = 22  # the days' numbers

    def __init__(self):
        super().__init__()
        self.setMouseTracking(True)
        self.setMinimumHeight(180)
        self._days: tuple[DayCash, ...] = ()
        self._average = 0
        self.hover = -1

    def set_days(self, days: tuple[DayCash, ...], average: int) -> None:
        self._days, self._average, self.hover = days, average, -1
        self.update()

    def _plot(self) -> QRectF:
        return QRectF(self.GUTTER, 8, max(self.width() - self.GUTTER, 1),
                      max(self.height() - 8 - self.LABELS, 1))

    def _index_at(self, x: float) -> int:
        plot = self._plot()
        if not self._days or not plot.left() <= x < plot.right():
            return -1
        return min(int((x - plot.left()) / (plot.width() / len(self._days))),
                   len(self._days) - 1)

    def mouseMoveEvent(self, event) -> None:
        index = self._index_at(event.position().x())
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
        mono = QFont("IBM Plex Mono")
        mono.setPixelSize(11)
        painter.setFont(mono)
        plot = self._plot()
        step = nice_step(max((d.amount for d in self._days), default=0))
        top = step * 2

        def y_of(amount: int) -> float:
            return plot.bottom() - amount / top * plot.height()

        for k in range(3):
            y = y_of(k * step)
            painter.setPen(QPen(QColor(tk["border"]), 1))
            painter.drawLine(plot.left(), y, plot.right(), y)
            painter.setPen(QColor(tk["muted"]))
            painter.drawText(QRectF(0, y - 8, self.GUTTER - 10, 16),
                             Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                             figure(k * step))
        if not self._days:
            return
        slot = plot.width() / len(self._days)
        bar = min(slot * 0.72, 28)
        every = 1 if slot >= 18 else 2
        soft = QColor(blend(tk["primary"], tk["surface"], 0.45))
        for i, day in enumerate(self._days):
            middle = plot.left() + slot * (i + 0.5)
            picked = i == self.hover
            painter.setPen(Qt.PenStyle.NoPen)
            if day.amount > 0:
                height = max(day.amount / top * plot.height(), 2)
                painter.setBrush(QColor(tk["primary"]) if picked else soft)
                painter.drawRoundedRect(QRectF(middle - bar / 2, plot.bottom() - height, bar,
                                               height), 2, 2)
            elif not day.open:
                painter.setBrush(QColor(tk["border_strong"]))
                painter.drawRect(QRectF(middle - bar / 2, plot.bottom() - 2, bar, 2))
            if i % every == 0 or picked:
                color = tk["text"] if picked else (tk["muted"] if day.open else tk["faint"])
                painter.setPen(QColor(color))
                painter.drawText(QRectF(middle - slot, plot.bottom() + 4, slot * 2,
                                        self.LABELS - 4), Qt.AlignmentFlag.AlignCenter,
                                 str(int(day.day[8:])))
        if self._average > 0:
            pen = QPen(QColor(tk["primary"]), 1, Qt.PenStyle.CustomDashLine)
            pen.setDashPattern([4, 3])
            painter.setPen(pen)
            y = y_of(self._average)
            painter.drawLine(plot.left(), y, plot.right(), y)


class CashCard(Card):
    def __init__(self):
        super().__init__("")
        self.set_subtitle(t["dashboard.cash_hint"])
        self.picked_day = caption()
        self.picked_day.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.picked_amount = label("", "readout", Qt.AlignmentFlag.AlignRight)
        readout = QVBoxLayout()
        readout.setSpacing(0)
        readout.addWidget(self.picked_day)
        readout.addWidget(self.picked_amount)
        self.side.addLayout(readout)
        self.chart = CashChart()
        self.chart.hovered.connect(self._pick)
        chart_box = QHBoxLayout()
        chart_box.setContentsMargins(PAD, 0, PAD, 12)
        chart_box.addWidget(self.chart)
        self.body.addLayout(chart_box)
        self.total = label("", "figure")
        self.more = link(t["dashboard.cash_link"])
        self.body.addWidget(foot(caption(t["dashboard.cash_total"]), self.total,
                                 link_button=self.more))
        self._days: tuple[DayCash, ...] = ()

    def set_days(self, days: tuple[DayCash, ...]) -> None:
        self._days = days
        open_days = [d for d in days if d.open]
        total = sum(d.amount for d in days)
        average = round(total / len(open_days)) if open_days else 0
        if days:
            month = int(days[0].day[5:7])
            self.title.setText(t["dashboard.cash"].format(month=t[f"month.{month}"].lower()))
        self.chart.set_days(days, average)
        self.total.setText(format_dzd(total))
        self._pick(-1)

    def _pick(self, index: int) -> None:
        """The day under the mouse, else today."""
        if not self._days:
            self.picked_day.clear()
            self.picked_amount.clear()
            return
        day = self._days[index]
        self.picked_day.setText(short_date(day.day))
        self.picked_amount.setText(format_dzd(day.amount) if day.open
                                   else t["dashboard.closed"])


# ----- the debts -----

class DebtorsCard(ListCard):
    open_student = Signal(int)
    collect = Signal(int)
    sort_changed = Signal(str)  # 'amount' or 'age'

    def __init__(self):
        super().__init__(t["dashboard.debtors"], t["dashboard.debtors_empty"], ROW_HEIGHT)
        segments = QFrame()
        segments.setObjectName("segments")
        line = QHBoxLayout(segments)
        line.setContentsMargins(3, 3, 3, 3)
        line.setSpacing(2)
        self.sorts = QButtonGroup(self)
        self.sort_buttons: dict[str, QPushButton] = {}
        for key in ("amount", "age"):
            button = QPushButton(t[f"dashboard.sort.{key}"])
            button.setObjectName("segment")
            button.setCheckable(True)
            button.setAutoDefault(False)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _on, k=key: self.sort_changed.emit(k))
            self.sorts.addButton(button)
            self.sort_buttons[key] = button
            line.addWidget(button)
        self.sort_buttons["amount"].setChecked(True)
        self.side.addWidget(segments, 0, Qt.AlignmentFlag.AlignVCenter)

        self.head = QFrame()
        self.head.setObjectName("tableHead")
        self.head.setFixedHeight(34)
        head = QHBoxLayout(self.head)
        head.setContentsMargins(PAD, 0, PAD, 0)
        head.setSpacing(12)
        self._columns(head, label(t["dashboard.col.student"].upper(), "colHead"),
                      label(t["dashboard.col.owed"].upper(), "colHead"),
                      label(t["dashboard.col.since"].upper(), "colHead"), QWidget())
        self.body.addWidget(self.head)
        self.place_rows()
        self.count_note = caption()
        self.more = link(t["dashboard.debtors_link"])
        self.footer = foot(self.count_note, link_button=self.more)
        self.body.addWidget(self.footer)
        self._total = 0

    @staticmethod
    def _columns(layout, name: QWidget, owed: QWidget, since: QWidget, action: QWidget) -> None:
        layout.addWidget(name, 1)
        layout.addWidget(fixed(owed, OWED_WIDTH, Qt.AlignmentFlag.AlignRight))
        layout.addSpacing(12)
        layout.addWidget(fixed(since, SINCE_WIDTH))
        layout.addWidget(fixed(action, ACTION_WIDTH, Qt.AlignmentFlag.AlignRight))

    def set_debtors(self, debtors: tuple[Debtor, ...], count: int, total: int) -> None:
        self._total = count
        self.set_subtitle(plural("dashboard.debtors_detail", count, amount=(
            f'<span style="color: {tokens()["danger"]}; font-family: \'IBM Plex Mono\'">'
            f"{html.escape(format_dzd(total))}</span>")) if count else "")
        self.head.setVisible(bool(debtors))
        self.footer.setVisible(bool(debtors))
        self.set_items([lambda d=d: self._row(d) for d in debtors])

    def rows_shown(self) -> None:
        self.count_note.setText(t["dashboard.debtors_foot"].format(shown=self.shown,
                                                                  total=self._total))

    def _row(self, d: Debtor) -> Row:
        row = Row(ROW_HEIGHT, lambda: self.open_student.emit(d.student_id))
        row.setToolTip(d.student_number)
        collect = QPushButton(t["dashboard.collect"].format(amount=format_dzd(d.owed_now)))
        collect.setObjectName("rowAction")
        collect.setAutoDefault(False)
        collect.clicked.connect(lambda: self.collect.emit(d.student_id))
        since = Badge(days_text(d.days_overdue),
                      "warning" if d.days_overdue >= LATE_DAYS else "neutral")
        self._columns(row.line, ElidedLabel(d.student_name, "rowTitle"),
                      label(format_dzd(d.owed_now), "owed"), since, collect)
        return row


# ----- the day -----

def session_state(s: DashboardSession, now: str) -> tuple[str, str]:
    """(label, badge kind): planned, under way, held or cancelled."""
    if s.status == "cancelled":
        return t["session_status.cancelled"], "neutral"
    if s.status == "held":
        return t["session_status.held"], "success"
    if s.start_time <= now < s.end_time:
        return t["dashboard.session_ongoing"], "info"
    return t["session_status.planned"], "info"


class SessionsCard(ListCard):
    def __init__(self):
        super().__init__(t["dashboard.sessions"], t["dashboard.sessions_empty"],
                         SESSION_ROW_HEIGHT)
        self.more = link(t["dashboard.sessions_link"])
        self.side.addWidget(self.more)
        self.place_rows()
        self.empty.setContentsMargins(PAD, 4, PAD, 16)

    def set_day(self, board: Dashboard) -> None:
        self.set_items([lambda s=s: self._row(s, board.now) for s in board.sessions])

    def _row(self, s: DashboardSession, now: str) -> Row:
        row = Row(SESSION_ROW_HEIGHT)
        cancelled = s.status == "cancelled"
        time = label(s.start_time, "rowTime")
        time.setFixedWidth(52)
        time.setProperty("struck", cancelled)
        title = ElidedLabel(s.group_title, "rowTitle", struck=cancelled)
        where = ElidedLabel(t["dashboard.session_line"].format(
            start=s.start_time, end=s.end_time, room=s.room, teacher=s.teacher), "caption")
        text = QVBoxLayout()
        text.setSpacing(0)
        text.addStretch()
        text.addWidget(title)
        text.addWidget(where)
        text.addStretch()
        state, kind = session_state(s, now)
        row.line.addWidget(time)
        row.line.addLayout(text, 1)
        row.line.addWidget(Badge(state, kind), 0, Qt.AlignmentFlag.AlignVCenter)
        return row


class FillBar(QWidget):
    """A group's seats taken, as a thin bar."""

    def __init__(self, enrolled: int, seats: int):
        super().__init__()
        self.setFixedSize(96, 6)
        self._rate = min(enrolled / seats, 1) if seats else 0

    def paintEvent(self, event) -> None:
        tk = tokens()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(tk["surface_alt"]))
        painter.drawRoundedRect(QRectF(self.rect()), 3, 3)
        if self._rate > 0:
            painter.setBrush(QColor(tk["info"]))
            painter.drawRoundedRect(QRectF(0, 0, max(self.width() * self._rate, 6), 6), 3, 3)


def free_text(g: GroupFill) -> str:
    free = max(g.seats - g.enrolled, 0)
    if free == 0:
        return t["dashboard.full"]
    return t["dashboard.free_1"] if free == 1 else t["dashboard.free_n"].format(count=free)


class GroupsCard(ListCard):
    def __init__(self):
        super().__init__(t["dashboard.free"], t["dashboard.groups_empty"], ROW_HEIGHT)
        self.more = link()
        self.side.addWidget(self.more)
        self.place_rows()

    def set_groups(self, fills: tuple[GroupFill, ...]) -> None:
        """The most free seats first: where a new student can go."""
        self.more.setText(plural("dashboard.groups_link", len(fills)) if fills else "")
        self.more.setVisible(bool(fills))
        order = sorted(fills, key=lambda g: (-(g.seats - g.enrolled), g.title.casefold()))
        self.set_items([lambda g=g: self._row(g) for g in order])

    def _row(self, g: GroupFill) -> Row:
        row = Row(ROW_HEIGHT)
        row.setToolTip(f"{g.enrolled} / {g.seats}")
        free = label(free_text(g), "figure", Qt.AlignmentFlag.AlignRight)
        if g.enrolled >= g.seats:
            free.setObjectName("mono")
        row.line.addWidget(ElidedLabel(g.title, "rowTitle"), 1)
        row.line.addWidget(FillBar(g.enrolled, g.seats))
        row.line.addWidget(fixed(free, 84, Qt.AlignmentFlag.AlignRight))
        return row


BACKUP_STATES = {"verified": ("check", "success"), "failed": ("x", "danger"),
                 "none": ("clock", "neutral")}  # icon and kind


class BackupCard(QFrame):

    def __init__(self):
        super().__init__()
        self.setObjectName("card")
        self.mark = QLabel()
        self.mark.setObjectName("statusIcon")
        self.mark.setFixedSize(28, 28)
        self.mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.text = QLabel()
        self.more = link(t["dashboard.backup_link"])
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 12, PAD, 12)
        layout.setSpacing(12)
        layout.addWidget(self.mark)
        layout.addWidget(self.text, 1)
        layout.addWidget(self.more)

    def set_status(self, status: str) -> None:
        name, kind = BACKUP_STATES.get(status, BACKUP_STATES["none"])
        self.mark.setPixmap(icon(name, kind, 32).pixmap(16, 16))
        self.mark.setProperty("kind", kind)
        self.mark.style().unpolish(self.mark)
        self.mark.style().polish(self.mark)
        self.text.setText(t[f"dashboard.backup.{status}"])


# ----- the page -----

class DashboardPage(QWidget):
    open_student = Signal(int)
    navigate = Signal(str)

    def __init__(self, conn, ctx: UserContext):
        super().__init__()
        self.setObjectName("page")
        self._conn = conn
        self._ctx = ctx
        self._board: Dashboard | None = None
        self._sort = "amount"

        self.day = caption()
        self.hello = label("", "pageTitle")
        self.header = QWidget()
        heading = QVBoxLayout(self.header)
        heading.setContentsMargins(0, 0, 0, 0)
        heading.setSpacing(2)
        heading.addWidget(self.hello)

        self.cash = CashCard() if allowed(ctx, "report.finance") else None
        self.debtors = DebtorsCard()
        self.sessions = SessionsCard()
        self.groups = GroupsCard()
        self.backup = BackupCard() if allowed(ctx, "backup.create") else None
        self.debtors.open_student.connect(self.open_student.emit)
        self.debtors.collect.connect(self._collect)
        self.debtors.sort_changed.connect(self._sorted)
        self.debtors.more.clicked.connect(lambda: self.navigate.emit("payments"))
        self.sessions.more.clicked.connect(lambda: self.navigate.emit("attendance"))
        self.groups.more.clicked.connect(lambda: self.navigate.emit("groups"))
        if self.cash is not None:
            self.cash.more.clicked.connect(lambda: self.navigate.emit("payments"))
        if self.backup is not None:
            self.backup.more.clicked.connect(lambda: self.navigate.emit("settings/backups"))

        # Each column: the cards that keep their size, then the lists that share the rest.
        self.columns = (
            ([c for c in (self.cash,) if c is not None], [self.debtors]),
            ([c for c in (self.backup,) if c is not None], [self.sessions, self.groups]),
        )
        left, right = QVBoxLayout(), QVBoxLayout()
        for column in (left, right):
            column.setSpacing(SPACING)
        if self.cash is not None:
            left.addWidget(self.cash)
        left.addWidget(self.debtors)
        right.addWidget(self.sessions)
        right.addWidget(self.groups)
        if self.backup is not None:
            right.addWidget(self.backup)
        for column in (left, right):
            column.addStretch()
        columns = QHBoxLayout()
        columns.setSpacing(SPACING)
        columns.addLayout(left, 3)
        columns.addLayout(right, 2)

        content = QWidget()
        content.setMaximumWidth(CONTENT_MAX)
        inner = QVBoxLayout(content)
        inner.setContentsMargins(0, 0, 0, 0)
        inner.setSpacing(SPACING)
        inner.addWidget(self.header)
        inner.addLayout(columns, 1)
        self.body = QWidget()
        body = QHBoxLayout(self.body)
        body.setContentsMargins(24, 16, 24, 16)
        body.addWidget(content, 1)
        body.addStretch()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._top_bar())
        layout.addWidget(self.body, 1)
        self._inner = inner
        self.refresh()

    def _top_bar(self) -> QFrame:
        """The page's name, and the two things the desk does most from here."""
        bar = QFrame()
        bar.setObjectName("topbar")
        bar.setFixedHeight(TOPBAR_HEIGHT)
        title = label(t["dashboard.title"], "topbarTitle")
        line = QHBoxLayout(bar)
        line.setContentsMargins(24, 0, 24, 0)
        line.setSpacing(8)
        line.addWidget(title)
        line.addSpacing(8)
        line.addWidget(self.day, 0, Qt.AlignmentFlag.AlignVCenter)
        line.addStretch()
        self.add_student = QPushButton(t["dashboard.add_student"])
        self.add_student.setIcon(icon("user-plus", "text", gap=15))
        self.add_student.setAutoDefault(False)
        self.add_student.clicked.connect(self._new_student)
        self.collect_payment = primary_button(t["dashboard.collect_payment"])
        self.collect_payment.setIcon(icon("wallet", "on_primary", gap=15))
        self.collect_payment.setAutoDefault(False)
        self.collect_payment.setDefault(False)
        self.collect_payment.clicked.connect(self._pick_and_collect)
        for button, action in ((self.add_student, "student.create"),
                               (self.collect_payment, "payment.record")):
            button.setIconSize(QSize(22, 16))  # 16 px drawn, 6 px before the label
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setVisible(allowed(self._ctx, action))
            line.addWidget(button)
        return bar

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.fit_rows()

    def showEvent(self, event) -> None:
        # The first resize arrives while the page is being shown, before it counts as
        # visible: fit again once it is.
        super().showEvent(event)
        self.fit_rows()

    def lists_height(self) -> int:
        """What the columns have, under the top bar and the greeting."""
        margins = self.body.layout().contentsMargins()
        # The greeting as laid out: its word-wrapped line may take one line or two.
        return (self.height() - TOPBAR_HEIGHT - margins.top() - margins.bottom()
                - self._inner.spacing() - self.header.height())

    def fit_rows(self) -> None:
        """As many rows in each list as the window leaves room for. Not before the page is
        on screen: until then its size is Qt's default, not the window's."""
        if not self.isVisible():
            return
        room = self.lists_height()
        for fixed_cards, lists in self.columns:
            cards = len(fixed_cards) + len(lists)
            left = (room - SPACING * (cards - 1)
                    - sum(card.sizeHint().height() for card in fixed_cards)
                    - sum(card.frame_height() for card in lists))
            shown = share_rows(max(left, 0), [card.count for card in lists],
                               [card.row_height for card in lists])
            for card, rows in zip(lists, shown, strict=True):
                card.show_rows(rows)

    def refresh(self) -> None:
        self.show_board(reports.dashboard(self._conn, self._ctx))

    def show_board(self, board: Dashboard) -> None:
        self._board = board
        self.day.setText(long_date(board.today))
        self.hello.setText(greeting(self._ctx.username, board.now))
        if self.cash is not None:
            self.cash.set_days(board.daily or ())
        self._show_debtors()
        self.sessions.set_day(board)
        self.groups.set_groups(board.groups)
        if self.backup is not None:
            self.backup.set_status(board.backup or "none")
        self.fit_rows()

    def _show_debtors(self) -> None:
        board = self._board
        debtors = board.oldest_debtors if self._sort == "age" else board.top_debtors
        self.debtors.set_debtors(debtors, board.debtors, board.debt_total)

    def _sorted(self, key: str) -> None:
        self._sort = key
        self._show_debtors()
        self.fit_rows()

    def _new_student(self) -> None:
        """« Ajouter un élève »: the new student's page opens once created, as from the
        students list."""
        dialog = StudentDialog(self._conn, self._ctx, parent=self)
        if not ask(dialog):
            return
        student = students.get(self._conn, self._ctx, dialog.student_id)
        toast(self, t["students.created"].format(name=student.full_name,
                                                 number=student.student_number))
        self.open_student.emit(student.id)

    def _pick_and_collect(self) -> None:
        """« Encaisser un paiement »: choose the student, then the payment dialog."""
        picker = StudentPicker(self._conn, self._ctx, parent=self)
        if ask(picker):
            self._collect(picker.student_id)

    def _collect(self, student_id: int) -> None:
        """« Encaisser »: the payment dialog, the amount late already typed; the receipt
        opens to be printed, as from the student's page."""
        student = students.get(self._conn, self._ctx, student_id)
        dialog = PaymentDialog(self._conn, self._ctx, student, parent=self)
        if not ask(dialog):
            return
        p = payments.get(self._conn, self._ctx, dialog.payment_id)
        toast(self, t["payments_tab.received"].format(amount=format_dzd(p.amount),
                                                      number=p.receipt_number))
        if p.receipt_id is not None and allowed(self._ctx, "print.document"):
            try:
                common.open_document(printing.receipt(self._conn, self._ctx, p.receipt_id))
            except (BusinessRuleError, OSError):
                QMessageBox.warning(self, t["app.name"], t["print.failed"])
        self.refresh()
