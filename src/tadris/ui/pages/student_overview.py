"""The student page keeps the essentials; the long lists open in a window.

GroupLines: one line per group the student is in now (trial or active): its status since its
entry, the month that runs (or comes next) with what is left to pay on it, and the attendance
in that group. SectionWindow: a list of the page (groups with their history, every session
with its attendance, every month, every payment) in a window, with all its actions."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
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
from tadris.ui.theme.status import kind_for
from tadris.ui.widgets.common import Badge


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


def month_text(e: Enrollment, month: Subscription | None) -> str:
    if month is None:
        return t["overview.trial"] if e.status == "trial" else t["overview.no_month"]
    left = (t["subscriptions.free"] if month.charge_id is None
            else t["overview.left"].format(amount=format_dzd(month.due)))
    return t["overview.month"].format(period=short_period(month.start_date, month.end_date),
                                      left=left)


def attendance_text(s: AttendanceSummary | None) -> str:
    if s is None or s.total == 0:
        return t["overview.no_attendance"]
    rate = s.rate_bp
    return t["overview.attendance"].format(
        rate=format_percent(rate) if rate is not None else "—", sessions=s.total,
        absent=s.absent)


class GroupLine(QFrame):
    def __init__(self, e: Enrollment, month: Subscription | None,
                 summary: AttendanceSummary | None):
        super().__init__()
        self.setObjectName("overviewLine")
        self.enrollment = e
        title = QLabel(e.group_title)
        title.setObjectName("rowTitle")
        status = Badge(t[f"enrollment_status.{e.status}"], kind_for("enrollment", e.status))
        since = QLabel(t["overview.since"].format(date=display_date(e.enrolled_on)))
        since.setObjectName("caption")
        head = QHBoxLayout()
        head.setSpacing(8)
        head.addWidget(title, 1)
        head.addWidget(since)
        head.addWidget(status)
        self.month = QLabel(month_text(e, month))
        self.month.setObjectName("caption")
        month_row = QHBoxLayout()
        month_row.setSpacing(8)
        month_row.addWidget(self.month, 1)
        if month is not None:
            month_row.addWidget(Badge(t[f"subscription_state.{month.state}"],
                                      kind_for("subscription", month.state)))
        self.attendance = QLabel(attendance_text(summary))
        self.attendance.setObjectName("caption")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 8)
        layout.setSpacing(2)
        layout.addLayout(head)
        layout.addLayout(month_row)
        layout.addWidget(self.attendance)


class GroupLines(QWidget):
    """The groups the student is in now, one line each, a rule between them."""

    def __init__(self):
        super().__init__()
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)
        self.empty = QLabel(t["overview.no_group"])
        self.empty.setObjectName("caption")
        self.empty.setWordWrap(True)
        self.lines: list[GroupLine] = []

    def set_lines(self, enrollments: list[Enrollment], months: list[Subscription],
                  attendance: dict[int, AttendanceSummary], today: str) -> None:
        while self._layout.count():
            widget = self._layout.takeAt(0).widget()
            if widget is not None and widget is not self.empty:
                widget.deleteLater()
        self.lines = []
        for i, e in enumerate(x for x in enrollments if x.is_live):
            if i:
                rule = QFrame()
                rule.setObjectName("cardRule")
                rule.setFixedHeight(1)
                self._layout.addWidget(rule)
            mine = [m for m in months if m.enrollment_id == e.id]
            line = GroupLine(e, current_month(mine, today), attendance.get(e.id))
            self.lines.append(line)
            self._layout.addWidget(line)
        self._layout.addWidget(self.empty)
        self.empty.setVisible(not self.lines)


class SectionWindow(QDialog):
    """One section of the student page, whole, in a window: its list and its actions."""

    def __init__(self, title: str, section: QWidget, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.section = section
        heading = QLabel(title)
        heading.setObjectName("dialogTitle")
        self.close_button = QPushButton(t["action.close"])
        self.close_button.setAutoDefault(False)
        self.close_button.clicked.connect(self.accept)
        actions = QHBoxLayout()
        actions.addStretch()
        actions.addWidget(self.close_button)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(16)
        layout.addWidget(heading)
        layout.addWidget(section, 1)
        layout.addLayout(actions)
        self.resize(980, 640)


def link_button(text: str = "") -> QPushButton:
    button = QPushButton(text)
    button.setObjectName("link")
    button.setAutoDefault(False)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    return button
