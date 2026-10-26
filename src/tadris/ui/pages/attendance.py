"""Présences: the week as a strip of days, then the chosen day's sessions as cards. Each card
carries its attendance button and, in its « ⋯ » menu, only the actions that fit it."""

from collections.abc import Callable
from datetime import date, datetime, timedelta

from PySide6.QtCore import QPoint, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractButton,
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from tadris.core import dates
from tadris.core.context import UserContext
from tadris.core.errors import BusinessRuleError
from tadris.core.permissions import allowed
from tadris.domain.models import Session
from tadris.i18n.fr import t
from tadris.services import groups, sessions, teachers
from tadris.ui.pages.attendance_entry import AttendanceView
from tadris.ui.pages.dashboard import ElidedLabel, capitalized, fixed, label
from tadris.ui.pages.timetable import week_start
from tadris.ui.session_dialogs import CancelSessionDialog, MakeupDialog, SubstituteDialog
from tadris.ui.theme import icon, tokens
from tadris.ui.widgets.common import Badge, PageBanner, ask, toast
from tadris.ui.widgets.date_edit import DateLineEdit
from tadris.ui.widgets.forms import ListDetailPage, caption
from tadris.ui.widgets.inputs import FilterButton, fill_combo, id_combo

WEEK_DAYS = 7
MAX_DOTS = 5
KEY_STEPS = {Qt.Key.Key_Left: -1, Qt.Key.Key_Right: 1, Qt.Key.Key_PageUp: -WEEK_DAYS,
             Qt.Key.Key_PageDown: WEEK_DAYS}

# A session's state on the page: its badge kind, and the colour of its dot and accent.
STATE_KIND = {"planned": "info", "ongoing": "info", "due": "warning", "held": "success",
              "cancelled": "neutral"}
STATE_COLOR = {"planned": "info", "ongoing": "primary", "due": "warning", "held": "success",
               "cancelled": "faint"}


def now_time() -> str:
    return f"{datetime.now():%H:%M}"


def session_state(s: Session, today: str, now: str) -> str:
    """planned, ongoing (under way now), due (over, attendance not taken), held, cancelled."""
    if s.status in ("held", "cancelled"):
        return s.status
    if s.date < today or (s.date == today and s.end_time <= now):
        return "due"
    if s.date == today and s.start_time <= now:
        return "ongoing"
    return "planned"


def day_title(day: date) -> str:
    """« Lundi 19 octobre »."""
    return t["sessions_page.day_title"].format(
        weekday=capitalized(t[f"weekday.{day.isoweekday()}"]), day=day.day,
        month=t[f"month.{day.month}"].lower())


def day_summary(states: list[str]) -> str:
    """« 3 séances · 1 annulée · 1 appel à faire »; empty for a day without sessions."""
    if not states:
        return ""
    count = len(states)
    parts = [t["sessions_page.count_1" if count == 1 else "sessions_page.count_n"].format(
        count=count)]
    cancelled = states.count("cancelled")
    if cancelled:
        parts.append(t["sessions_page.count_cancelled"].format(count=cancelled))
    due = states.count("due")
    if due:
        parts.append(t["sessions_page.count_due"].format(count=due))
    return " · ".join(parts)


def note(s: Session) -> str:
    notes = []
    if s.makeup_of_date:
        notes.append(t["sessions_page.note.makeup_of"].format(
            date=dates.display_date(s.makeup_of_date)))
    if s.status == "cancelled" and s.cancellation_reason:
        notes.append(s.cancellation_reason)
    if s.makeup_date:
        notes.append(t["sessions_page.note.made_up"].format(
            date=dates.display_date(s.makeup_date)))
    return " · ".join(notes)


class DayChip(QAbstractButton):
    """A day of the week strip: « lun. », the day's number, and a dot per session in the
    colour of its state. Today is outlined."""

    HEIGHT = 68

    def __init__(self):
        super().__init__()
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(self.HEIGHT)
        self.setMinimumWidth(52)
        self.day = date.today()
        self.states: list[str] = []
        self.is_today = False

    def set_day(self, day: date, states: list[str], is_today: bool) -> None:
        self.day, self.states, self.is_today = day, states, is_today
        self.setToolTip(f"{day_title(day)}\n{day_summary(states) or t['sessions_page.none']}")
        self.update()

    def sizeHint(self) -> QSize:
        return QSize(80, self.HEIGHT)

    def keyPressEvent(self, event) -> None:
        if event.key() in KEY_STEPS:
            event.ignore()  # the page moves the day; a button group would only move focus
        else:
            super().keyPressEvent(event)

    def paintEvent(self, event) -> None:
        tk = tokens()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        checked = self.isChecked()
        if checked:
            fill, border, ink = tk["primary"], tk["primary"], tk["on_primary"]
        else:
            fill = tk["surface_alt"] if self.underMouse() else tk["surface"]
            border = tk["primary"] if self.is_today else tk["border"]
            ink = tk["text"] if self.states else tk["faint"]
        width = 2 if self.hasFocus() and not checked else 1
        painter.setPen(QPen(QColor(tk["focus"] if width == 2 else border), width))
        painter.setBrush(QColor(fill))
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 10, 10)

        font = QFont(self.font())
        font.setPixelSize(11)
        font.setWeight(QFont.Weight.DemiBold if self.is_today else QFont.Weight.Medium)
        painter.setFont(font)
        painter.setPen(QColor(ink if checked else tk["primary"] if self.is_today
                              else tk["muted"]))
        painter.drawText(QRectF(0, 8, self.width(), 14), Qt.AlignmentFlag.AlignCenter,
                         t[f"day_short.{self.day.isoweekday()}"])
        font.setPixelSize(19)
        font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(font)
        painter.setPen(QColor(ink))
        painter.drawText(QRectF(0, 22, self.width(), 26), Qt.AlignmentFlag.AlignCenter,
                         str(self.day.day))

        shown = self.states[:MAX_DOTS]
        size, gap = 6, 4
        left = (self.width() - len(shown) * size - (len(shown) - 1) * gap) / 2
        painter.setPen(Qt.PenStyle.NoPen)
        for i, state in enumerate(shown):
            color = QColor(tk["on_primary"] if checked else tk[STATE_COLOR[state]])
            painter.setBrush(color)
            painter.drawEllipse(QRectF(left + i * (size + gap), 52, size, size))


class RecordBar(QWidget):
    """How many students have their attendance recorded, as a thin bar."""

    def __init__(self, done: int, total: int, color: str):
        super().__init__()
        self.setFixedSize(64, 6)
        self._rate = min(done / total, 1) if total else 0
        self._color = color

    def paintEvent(self, event) -> None:
        tk = tokens()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(tk["surface_alt"]))
        painter.drawRoundedRect(QRectF(self.rect()), 3, 3)
        if self._rate > 0:
            painter.setBrush(QColor(tk[self._color]))
            painter.drawRoundedRect(QRectF(0, 0, max(self.width() * self._rate, 6), 6), 3, 3)


class NowLine(QWidget):
    """« Maintenant · 15:42 » and a line, between the sessions over and those to come."""

    def __init__(self, now: str):
        super().__init__()
        self.setFixedHeight(22)
        self.text = t["sessions_page.now"].format(time=now)

    def paintEvent(self, event) -> None:
        tk = tokens()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        font = QFont(self.font())
        font.setPixelSize(11)
        font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(font)
        color = QColor(tk["primary"])
        painter.setPen(color)
        middle = self.height() / 2
        text_width = painter.fontMetrics().horizontalAdvance(self.text)
        painter.drawText(QRectF(4, 0, text_width + 2, self.height()),
                         Qt.AlignmentFlag.AlignVCenter, self.text)
        painter.setBrush(color)
        painter.drawEllipse(QRectF(text_width + 14, middle - 3, 6, 6))
        painter.setPen(QPen(color, 1.5))
        painter.drawLine(int(text_width + 20), int(middle), self.width(), int(middle))


class SessionCard(QFrame):
    """One session: a coloured accent for its state, the time, the group, room and teacher,
    its badge, the attendance recorded, its main button and the « ⋯ » menu.

    A click anywhere else on the card opens the attendance. `act(key, session)` runs an
    action: open, cancel, restore, makeup or substitute."""

    def __init__(self, s: Session, state: str, today: str, manages: bool,
                 act: Callable[[str, Session], None]):
        super().__init__()
        self.session = s
        self.state = state
        self._act = act
        cancelled = state == "cancelled"
        self.setObjectName("sessionCard")
        self.setProperty("state", state)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

        accent = QFrame()
        accent.setObjectName("sessionAccent")
        accent.setProperty("state", state)
        accent.setFixedWidth(4)
        self.start = label(s.start_time, "cardTime")
        self.start.setProperty("struck", cancelled)
        self.end = label(s.end_time, "mono")
        times = QVBoxLayout()
        times.setSpacing(0)
        times.addStretch()
        times.addWidget(self.start)
        times.addWidget(self.end)
        times.addStretch()
        time_box = QWidget()
        time_box.setFixedWidth(76)
        time_box.setLayout(times)

        self.title = ElidedLabel(s.group_name, "cardTitle", struck=cancelled)
        self.where = ElidedLabel(f"{s.room} · {s.teacher}", "caption")
        where = QHBoxLayout()
        where.setSpacing(8)
        where.addWidget(self.where)
        self.substitute_badge = Badge(t["sessions_page.substitute_badge"], "warning")
        self.substitute_badge.setVisible(s.substitute)
        where.addWidget(self.substitute_badge)
        where.addStretch()
        self.note = ElidedLabel(note(s), "caption")
        keep = self.note.sizePolicy()
        keep.setRetainSizeWhenHidden(True)
        self.note.setSizePolicy(keep)
        self.note.setVisible(bool(self.note.text()))
        text = QVBoxLayout()
        text.setSpacing(2)
        text.addStretch()
        text.addWidget(self.title)
        text.addLayout(where)
        text.addWidget(self.note)
        text.addStretch()

        self.badge = Badge(t[f"sessions_page.state.{state}"], STATE_KIND[state])
        self.count = label("" if cancelled else t["sessions_page.recorded"].format(
            done=s.attendance_count, total=s.expected), "figure")
        progress = QVBoxLayout()
        progress.setSpacing(4)
        progress.addStretch()
        progress.addWidget(self.count)
        if not cancelled:
            progress.addWidget(RecordBar(s.attendance_count, s.expected,
                                         "success" if state == "held" else STATE_COLOR[state]))
        progress.addStretch()
        progress_box = QWidget()
        progress_box.setFixedWidth(84)
        progress_box.setLayout(progress)

        self.main_key: str | None = None
        self.main = self._main_button(today, manages)
        self.more = QPushButton()
        self.more.setObjectName("iconButton")
        self.more.setIcon(icon("ellipsis", "text"))
        self.more.setIconSize(QSize(18, 18))
        self.more.setAutoDefault(False)
        self.more.setToolTip(t["sessions_page.more"])
        self.menu = QMenu(self)
        self.actions_by_key = {}
        for key in self._menu_keys(manages):
            action = self.menu.addAction(t[f"sessions_page.{key}"])
            action.triggered.connect(lambda _c=False, k=key: self._act(k, self.session))
            self.actions_by_key[key] = action
        self.more.clicked.connect(lambda: self.menu.exec(
            self.more.mapToGlobal(QPoint(0, self.more.height() + 4))))
        policy = self.more.sizePolicy()
        policy.setRetainSizeWhenHidden(True)
        self.more.setSizePolicy(policy)
        self.more.setVisible(bool(self.actions_by_key))

        line = QHBoxLayout(self)
        line.setContentsMargins(14, 14, 14, 14)
        line.setSpacing(14)
        line.addWidget(accent)
        line.addWidget(time_box)
        line.addLayout(text, 1)
        line.addWidget(fixed(self.badge, 116))
        line.addWidget(progress_box)
        main_box = fixed(self.main or QWidget(), 148, Qt.AlignmentFlag.AlignRight)
        line.addWidget(main_box)
        line.addWidget(self.more, 0, Qt.AlignmentFlag.AlignVCenter)

    def _main_button(self, today: str, manages: bool) -> QPushButton | None:
        """Faire l'appel (in colour when it is time), Voir l'appel, Voir la liste for a day to
        come, or Rattrapage… for a cancelled session not made up yet."""
        s = self.session
        if self.state == "cancelled":
            if not manages or s.makeup_id is not None:
                return None
            key, primary = "makeup", False
        elif self.state == "held":
            key, primary = "view", False
        elif s.date > today:
            key, primary = "roster", False
        else:
            key, primary = "take", self.state in ("ongoing", "due")
        button = QPushButton(t[f"sessions_page.{key}"])
        if primary:
            button.setProperty("variant", "primary")
        elif key == "roster":
            button.setProperty("variant", "ghost")
        button.setAutoDefault(False)
        action = "makeup" if key == "makeup" else "open"
        button.clicked.connect(lambda: self._act(action, self.session))
        self.main_key = key
        return button

    def _menu_keys(self, manages: bool) -> list[str]:
        s = self.session
        if not manages:
            return []
        if s.status == "cancelled":
            return ["restore"] if s.makeup_id is None else []
        keys = ["substitute"]
        if s.status == "planned" and not s.attendance_count:
            keys.append("cancel")
        return keys

    def mouseReleaseEvent(self, event) -> None:
        if (event.button() == Qt.MouseButton.LeftButton
                and self.rect().contains(event.position().toPoint())):
            self._act("open", self.session)
        else:
            super().mouseReleaseEvent(event)


class SessionsView(QWidget):
    """The week strip and the chosen day's session cards."""

    opened = Signal(int)

    def __init__(self, conn, ctx: UserContext):
        super().__init__()
        self._conn = conn
        self._ctx = ctx
        self.setObjectName("page")
        self._sessions: dict[int, Session] = {}
        self.manages = allowed(ctx, "session.manage")
        self.cards: list[SessionCard] = []

        title = QLabel(t["nav.attendance"])
        title.setObjectName("pageTitle")
        self.group = id_combo([])
        self.teacher = id_combo([])
        self.filters = FilterButton()
        self.filters.add_filter(t["sessions_page.filter.group"], self.group)
        self.filters.add_filter(t["sessions_page.filter.teacher"], self.teacher)
        self.today = QPushButton(t["sessions_page.today"])
        self.today.setAutoDefault(False)
        self.today.clicked.connect(lambda: self.on.set_value(dates.today()))
        self.on = DateLineEdit()
        self.on.setFixedWidth(150)
        self.on.set_value(dates.today())
        self.on.textChanged.connect(lambda _text: self._date_changed())
        head = QHBoxLayout()
        head.setSpacing(8)
        head.addWidget(title)
        head.addStretch()
        head.addWidget(self.today)
        head.addWidget(self.on)
        head.addSpacing(8)
        head.addWidget(self.filters)

        self.previous = self._nav_button("chevron-left", t["sessions_page.previous_week"])
        self.previous.clicked.connect(lambda: self._move(-WEEK_DAYS))
        self.following = self._nav_button("chevron-right", t["sessions_page.next_week"])
        self.following.clicked.connect(lambda: self._move(WEEK_DAYS))
        self.chips = [DayChip() for _ in range(WEEK_DAYS)]
        self._chip_group = QButtonGroup(self)
        self._chip_group.setExclusive(True)
        strip = QHBoxLayout()
        strip.setSpacing(8)
        strip.addWidget(self.previous)
        for chip in self.chips:
            self._chip_group.addButton(chip)
            chip.clicked.connect(lambda _c=False, c=chip: self.on.set_value(c.day))
            strip.addWidget(chip, 1)
        strip.addWidget(self.following)

        self.period = label("", "sectionTitle")
        self.summary = caption()
        day_head = QHBoxLayout()
        day_head.setSpacing(12)
        day_head.addWidget(self.period)
        day_head.addWidget(self.summary, 0, Qt.AlignmentFlag.AlignBaseline)
        day_head.addStretch()

        self.error = PageBanner()
        self.empty = QLabel()
        self.empty.setObjectName("emptyState")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty.setWordWrap(True)
        self._cards = QVBoxLayout()
        self._cards.setContentsMargins(0, 0, 0, 0)
        self._cards.setSpacing(8)
        holder = QWidget()
        column = QVBoxLayout(holder)
        column.setContentsMargins(0, 0, 0, 0)
        column.addLayout(self._cards)
        column.addWidget(self.empty)
        column.addStretch()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(holder)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 16)
        layout.setSpacing(14)
        layout.addLayout(head)
        layout.addLayout(strip)
        layout.addWidget(self.error)
        layout.addLayout(day_head)
        layout.addWidget(scroll, 1)

        self.load_filters()
        for combo in (self.group, self.teacher):
            combo.currentIndexChanged.connect(lambda _i: self.refresh())
        self.refresh()

    @staticmethod
    def _nav_button(name: str, tip: str) -> QPushButton:
        button = QPushButton()
        button.setObjectName("iconButton")
        button.setIcon(icon(name, "text"))
        button.setIconSize(QSize(18, 18))
        button.setFixedHeight(DayChip.HEIGHT)
        button.setAutoDefault(False)
        button.setToolTip(tip)
        return button

    def load_filters(self) -> None:
        fill_combo(self.group, [(t["sessions_page.all_groups"], None)] + [
            (g.title, g.id) for g in groups.search(self._conn, self._ctx)
            if g.status != "closed"], self.group.currentData())
        fill_combo(self.teacher, [(t["sessions_page.all_teachers"], None)] + [
            (teacher.full_name, teacher.id) for teacher in teachers.search(self._conn, self._ctx)
        ], self.teacher.currentData())
        self.filters.update_count()

    def selected_day(self) -> date:
        return self.on.value() or dates.today()

    def refresh(self) -> None:
        day = self.selected_day()
        first = week_start(day)
        listed = sessions.listing(self._conn, self._ctx, first, first + timedelta(days=6),
                                  group_id=self.group.currentData(),
                                  teacher_id=self.teacher.currentData())
        self._sessions = {s.id: s for s in listed}
        today, now = dates.iso(dates.today()), now_time()
        states = {s.id: session_state(s, today, now) for s in listed}
        for i, chip in enumerate(self.chips):
            on = first + timedelta(days=i)
            chip.set_day(on, [states[s.id] for s in listed if s.date == dates.iso(on)],
                         dates.iso(on) == today)
            chip.setChecked(on == day)

        shown = [s for s in listed if s.date == dates.iso(day)]
        self.period.setText(day_title(day))
        self.summary.setText(day_summary([states[s.id] for s in shown]))
        self._clear_cards()
        now_at = None
        if dates.iso(day) == today and shown:
            now_at = next((i for i, s in enumerate(shown) if s.start_time > now), len(shown))
        for i, s in enumerate(shown):
            if i == now_at:
                self._cards.addWidget(NowLine(now))
            card = SessionCard(s, states[s.id], today, self.manages, self._act)
            self.cards.append(card)
            self._cards.addWidget(card)
        if now_at == len(shown):
            self._cards.addWidget(NowLine(now))
        self.empty.setText(t["sessions_page.day_empty"] if listed else t["sessions_page.empty"])
        self.empty.setVisible(not shown)

    def _clear_cards(self) -> None:
        self.cards = []
        while self._cards.count():
            widget = self._cards.takeAt(0).widget()
            if widget is not None:
                widget.hide()  # deleteLater() waits for the event loop: gone from view now
                widget.deleteLater()

    def card(self, session_id: int) -> SessionCard | None:
        return next((c for c in self.cards if c.session.id == session_id), None)

    def _move(self, days: int) -> None:
        self.on.set_value(self.selected_day() + timedelta(days=days))

    def keyPressEvent(self, event) -> None:
        """← → a day, Page précédente / suivante a week: keys the date field and the
        filters do not use reach the page."""
        step = KEY_STEPS.get(event.key())
        if step is None:
            super().keyPressEvent(event)
        else:
            self._move(step)

    def _date_changed(self) -> None:
        if self.on.value() is not None:
            self.refresh()

    def _act(self, key: str, s: Session) -> None:
        if key == "open":
            self.opened.emit(s.id)
        else:
            getattr(self, f"_{key}")(s)

    def _run(self, action, *args):
        """A service action; a BusinessRuleError shows in the banner. None when refused."""
        try:
            result = action(*args)
        except BusinessRuleError as exc:
            self.error.show_error(exc.message)
            return None
        self.error.clear_error()
        return result if result is not None else True

    def _done(self, message: str) -> None:
        self.error.clear_error()
        self.refresh()
        toast(self, message)

    def _cancel(self, s: Session) -> None:
        if ask(CancelSessionDialog(self._conn, self._ctx, s, parent=self)):
            self._done(t["sessions_page.cancelled"].format(group=s.group_name))

    def _restore(self, s: Session) -> None:
        if self._run(sessions.restore, self._conn, self._ctx, s.id) is not None:
            self._done(t["sessions_page.restored"].format(group=s.group_name))

    def _makeup(self, s: Session) -> None:
        dialog = MakeupDialog(self._conn, self._ctx, s, parent=self)
        if ask(dialog):
            makeup = sessions.get(self._conn, self._ctx, dialog.makeup_id)
            self._done(t["sessions_page.made_up"].format(
                group=s.group_name, date=dates.display_date(makeup.date),
                start=makeup.start_time))

    def _substitute(self, s: Session) -> None:
        if ask(SubstituteDialog(self._conn, self._ctx, s, parent=self)):
            self._done(t["sessions_page.teacher_set"].format(group=s.group_name))


class AttendancePage(ListDetailPage):
    """Présences in the sidebar: the sessions, and a session's attendance in place of them."""

    def __init__(self, conn, ctx: UserContext):
        super().__init__(SessionsView(conn, ctx),
                         lambda session_id: AttendanceView(conn, ctx, session_id))

    @property
    def sessions(self) -> SessionsView:
        return self.list

    def has_unsaved(self) -> bool:
        """A session's attendance is open with marks not saved yet."""
        return self.detail is not None and self.detail.dirty()

    def refresh(self) -> None:
        if self.detail is None:
            self.list.load_filters()
        super().refresh()
