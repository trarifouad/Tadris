"""The student page keeps the essentials; the long lists open in a window (SectionWindow).

GroupLines: one tile per group the student is in now (trial or active): its status, its
subject and entry date, then the month that runs (or comes next), what is left to pay on it,
and the attendance in that group."""

from datetime import date, timedelta

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from tadris.core.dates import display_date, short_period
from tadris.core.money import format_dzd
from tadris.core.percent import format_percent
from tadris.domain.models import AttendanceSummary, Enrollment, Subscription
from tadris.i18n.fr import t
from tadris.ui.pages.dues_view import DUE_SOON_DAYS
from tadris.ui.standing import standing_badge
from tadris.ui.theme import icon
from tadris.ui.widgets.common import Badge, primary_button


def current_month(months: list[Subscription], today: str) -> Subscription | None:
    """Of one enrollment's months: the one running today, else the next to come, else the
    latest. Cancelled months are left out."""
    kept = [m for m in months if m.status != "cancelled"]
    running = [m for m in kept if m.start_date <= today < m.end_date]
    if running:
        return running[0]
    coming = sorted((m for m in kept if m.start_date > today), key=lambda m: m.start_date)
    if coming:
        return coming[0]
    return max(kept, key=lambda m: m.start_date, default=None)


def latest_month(months: list[Subscription]) -> Subscription | None:
    """Of one enrollment's months, the last one (cancelled months left out)."""
    return max((m for m in months if m.status != "cancelled"), key=lambda m: m.end_date,
               default=None)


def group_badge(e: Enrollment, latest: Subscription | None) -> tuple[str, str, str]:
    """The one badge of a group line, as on the Abonnements page (see ui.standing), from its
    latest month; a trial, which has no month, is « Essai » (grey)."""
    if latest is None and e.status == "trial":
        return t["enrollment_status.trial"], "neutral", ""
    return standing_badge(latest)


def month_cells(e: Enrollment, month: Subscription | None, ahead: list[Subscription],
                today: str, left: dict[int, int]) -> tuple[str, str, str, str]:
    """The month's two cells: (heading, period, left to pay, the amount's tone). Months paid
    ahead (`ahead`, after `month`) only push the period's end and add what is left on them.
    `left`: what is left on each charge after the student's credit (as in « À payer »).
    Without a month, the period says why and the amount is a dash. What is left is coloured
    as in « À payer »: a month's charge falls due on its start, late from that day (red),
    soon within DUE_SOON_DAYS (amber); the first month with something left decides."""
    if month is None:
        if e.status == "trial":
            return t["overview.metric.month"], t["overview.trial"], "—", "neutral"
        return t["overview.metric.month"], t["overview.no_month"], "—", "danger"
    heading = t[{"upcoming": "overview.metric.month_next",
                 "ended": "overview.metric.month_last"}.get(month.state,
                                                            "overview.metric.month")]
    shown = [month, *ahead]
    period = short_period(month.start_date, max(m.end_date for m in shown))
    if month.charge_id is None:
        return heading, period, t["subscriptions.free"], "neutral"
    owing = [m for m in shown if left.get(m.charge_id, 0)]
    if not owing:
        return heading, period, t["overview.paid"], "success"
    first = owing[0].start_date
    soon = (date.fromisoformat(today) + timedelta(days=DUE_SOON_DAYS)).isoformat()
    kind = "danger" if first <= today else "warning" if first <= soon else "neutral"
    return heading, period, format_dzd(sum(left[m.charge_id] for m in owing)), kind


def attendance_cells(s: AttendanceSummary | None) -> tuple[str, str]:
    """(the rate, its detail); a dash before the first session marked."""
    if s is None or s.total == 0:
        return "—", t["overview.no_attendance"]
    rate = s.rate_bp
    return (format_percent(rate) if rate is not None else "—",
            t["overview.attendance_detail"].format(sessions=s.total, absent=s.absent))


def metric(heading: str, value: str, kind: str = "neutral", detail: str = "") -> tuple:
    """A small heading over its value (and a detail line): one cell of a group's tile."""
    box = QVBoxLayout()
    box.setSpacing(2)
    label = QLabel(heading.upper())
    label.setObjectName("metricLabel")
    shown = QLabel(value)
    shown.setObjectName("metricValue")
    shown.setProperty("kind", kind)
    box.addWidget(label)
    box.addWidget(shown)
    extra = None
    if detail:
        extra = QLabel(detail)
        extra.setObjectName("caption")
        box.addWidget(extra)
    box.addStretch()
    return box, shown, extra


class GroupLine(QFrame):
    """One group, in a tile: its name and status, its subject and entry date, then three
    cells: the month, what is left to pay on it, the attendance."""

    def __init__(self, e: Enrollment, month: Subscription | None, ahead: list[Subscription],
                 latest: Subscription | None, summary: AttendanceSummary | None, today: str,
                 left: dict[int, int]):
        super().__init__()
        self.setObjectName("groupTile")
        self.enrollment = e
        title = QLabel(e.group_name)
        title.setObjectName("tileTitle")
        label, kind, tip = group_badge(e, latest)
        self.badge = Badge(label, kind)
        self.badge.setToolTip(tip)
        head = QHBoxLayout()
        head.setSpacing(8)
        head.addWidget(title, 1)
        head.addWidget(self.badge, 0, Qt.AlignmentFlag.AlignTop)
        self.subtitle = QLabel(t["overview.subtitle"].format(
            subject=e.subject, level=e.group_level, date=display_date(e.enrolled_on)))
        self.subtitle.setObjectName("caption")

        heading, period, owed, left_kind = month_cells(e, month, ahead, today, left)
        rate, detail = attendance_cells(summary)
        cells = QHBoxLayout()
        cells.setSpacing(16)
        renew = month is None and e.status != "trial"  # « à renouveler » in red
        box, self.period, _ = metric(heading, period, "danger" if renew else "neutral")
        cells.addLayout(box, 3)
        box, self.left, _ = metric(t["overview.metric.left"], owed, left_kind)
        cells.addLayout(box, 2)
        box, self.attendance, self.attendance_detail = metric(
            t["overview.metric.attendance"], rate, detail=detail)
        cells.addLayout(box, 3)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(2)
        layout.addLayout(head)
        layout.addWidget(self.subtitle)
        layout.addSpacing(10)
        layout.addLayout(cells)


class EmptyState(QFrame):
    """What a card shows when it has nothing yet: an icon, a title, one sentence on why,
    and the next step as a button (hidden when the user cannot take it)."""

    def __init__(self, icon_name: str):
        super().__init__()
        self.setObjectName("emptyPanel")
        mark = QLabel()
        mark.setObjectName("emptyIcon")
        mark.setFixedSize(48, 48)
        mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mark.setPixmap(icon(icon_name, "primary", 48).pixmap(22, 22))
        self.title = QLabel()
        self.title.setObjectName("emptyTitle")
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.text = QLabel()
        self.text.setObjectName("caption")
        self.text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.text.setWordWrap(True)
        self.action = primary_button("")
        self.action.setObjectName("rowAction")  # the size of a card's buttons
        self.action.setDefault(False)
        self.action.setAutoDefault(False)
        self.action.setCursor(Qt.CursorShape.PointingHandCursor)
        self.action.hide()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(6)
        layout.addStretch()
        layout.addWidget(mark, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addSpacing(6)
        layout.addWidget(self.title)
        layout.addWidget(self.text)
        layout.addSpacing(8)
        layout.addWidget(self.action, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addStretch()

    def set_message(self, title: str, text: str, action: str = "") -> None:
        """`action`: the button's label; empty, no button."""
        self.title.setText(title)
        self.text.setText(text)
        self.action.setText(action)
        self.action.setVisible(bool(action))


class GroupLines(QWidget):
    """The groups the student is in now, one tile each; without any, an empty state that
    says why and offers the next step (set by the page: it knows the registration)."""

    def __init__(self):
        super().__init__()
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(8)
        self.empty = EmptyState("layers")
        self.empty.set_message(t["overview.empty.title"], t["overview.no_group"])
        self.lines: list[GroupLine] = []

    def set_lines(self, enrollments: list[Enrollment], months: list[Subscription],
                  attendance: dict[int, AttendanceSummary], today: str,
                  left: dict[int, int]) -> None:
        """left: what is left on each charge after the student's credit."""
        while self._layout.count():
            widget = self._layout.takeAt(0).widget()
            if widget is not None and widget is not self.empty:
                widget.deleteLater()
        self.lines = []
        for e in (x for x in enrollments if x.is_live):
            mine = [m for m in months if m.enrollment_id == e.id]
            month = current_month(mine, today)
            ahead = sorted((m for m in mine if month and m.status != "cancelled"
                            and m.start_date > month.start_date), key=lambda m: m.start_date)
            line = GroupLine(e, month, ahead, latest_month(mine), attendance.get(e.id), today,
                             left)
            self.lines.append(line)
            self._layout.addWidget(line)
        # The tiles stay at the top; the empty state takes the card's room, centered.
        self._layout.addWidget(self.empty, 1)
        self.empty.setVisible(not self.lines)
        if self.lines:
            self._layout.addStretch()


def link_button(text: str = "") -> QPushButton:
    button = QPushButton(text)
    button.setObjectName("link")
    button.setAutoDefault(False)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    return button
