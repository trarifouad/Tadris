"""Taking a session's attendance: one line per student, a status button for each."""

from datetime import date

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from tadris.core import dates
from tadris.core.context import UserContext
from tadris.core.errors import BusinessRuleError
from tadris.core.permissions import allowed
from tadris.domain.models import ATTENDANCE_STATUSES, RosterLine
from tadris.i18n.fr import t
from tadris.services import attendance, printing, sessions
from tadris.ui.theme.status import kind_for
from tadris.ui.widgets import common
from tadris.ui.widgets.common import Badge, PageBanner, confirm, primary_button, toast
from tadris.ui.widgets.forms import HeaderCard, caption, padded
from tadris.ui.widgets.tables import fit_columns, frozen_columns, item, ruled_table


class MarkButtons(QWidget):
    """Présent, En retard, Absent, Excusé: at most one checked."""

    changed = Signal()

    def __init__(self, status: str | None, enabled: bool):
        super().__init__()
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.buttons: dict[str, QPushButton] = {}
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(6)
        for status_key in ATTENDANCE_STATUSES:
            button = QPushButton(t[f"attendance_status.{status_key}"])
            button.setObjectName("mark")
            button.setProperty("kind", kind_for("attendance", status_key))
            button.setCheckable(True)
            button.setAutoDefault(False)
            button.setEnabled(enabled)
            button.ensurePolished()  # measure with the theme's padding and font
            button.setMinimumWidth(button.sizeHint().width())
            self.group.addButton(button)
            self.buttons[status_key] = button
            layout.addWidget(button)
        layout.addStretch()
        if status is not None:
            self.buttons[status].setChecked(True)
        self.group.buttonClicked.connect(lambda _b: self.changed.emit())

    def status(self) -> str | None:
        for key, button in self.buttons.items():
            if button.isChecked():
                return key
        return None

    def set_status(self, status: str) -> None:
        self.buttons[status].setChecked(True)
        self.changed.emit()


class AttendanceView(QWidget):
    back = Signal()

    def __init__(self, conn, ctx: UserContext, session_id: int):
        super().__init__()
        self._conn = conn
        self._ctx = ctx
        self.session_id = session_id
        self.setObjectName("page")
        self._marks: dict[int, MarkButtons] = {}
        self._saved: dict[int, str | None] = {}

        self.back_button = QPushButton(t["attendance_view.back"])
        self.back_button.setObjectName("backLink")
        self.back_button.setProperty("variant", "ghost")
        self.back_button.setAutoDefault(False)
        self.back_button.clicked.connect(self._back)
        back_row = QHBoxLayout()
        back_row.addWidget(self.back_button)
        back_row.addStretch()

        self.header = HeaderCard()
        self.status = self.header.add_meta(Badge())
        self.when = self.header.add_meta(caption())
        self.where = self.header.add_meta(caption())
        self.header.close_meta()
        self.print_sheet = self.header.add_action(QPushButton(t["attendance_view.print"]))
        self.print_sheet.clicked.connect(self._print)
        self.print_sheet.setVisible(allowed(ctx, "print.document"))
        self.error = PageBanner()
        self.notice = caption()
        self.notice.setWordWrap(True)

        self.summary = QLabel()
        self.summary.setObjectName("sectionTitle")
        self.all_present = QPushButton(t["attendance_view.all_present"])
        self.all_present.setAutoDefault(False)
        self.all_present.clicked.connect(self._all_present)
        self.save = primary_button(t["action.save"])
        self.save.setDefault(False)
        self.save.clicked.connect(self._save)
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        toolbar.addWidget(self.summary)
        toolbar.addStretch()
        toolbar.addWidget(self.all_present)
        toolbar.addWidget(self.save)

        self.table = ruled_table([t["attendance_view.col.student"],
                                  t["attendance_view.col.number"],
                                  t["attendance_view.col.note"],
                                  t["attendance_view.col.mark"]])
        fit_columns(self.table, stretch=(0, 2))
        self.empty = QLabel(t["attendance_view.empty"])
        self.empty.setObjectName("emptyState")
        self.empty.setWordWrap(True)

        body = QVBoxLayout()
        body.setSpacing(12)
        body.addWidget(self.notice)
        body.addLayout(toolbar)
        body.addWidget(self.table, 1)
        body.addWidget(self.empty)
        content = QWidget()
        content.setLayout(body)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 14, 24, 24)
        layout.setSpacing(16)
        layout.addLayout(back_row)
        layout.addWidget(self.error)
        layout.addWidget(self.header)
        layout.addWidget(padded(content), 1)
        self.refresh()

    # ----- loading -----

    def refresh(self) -> None:
        s = sessions.get(self._conn, self._ctx, self.session_id)
        self.session = s
        self.header.title.setText(s.group_title)
        self.status.setText(t[f"session_status.{s.status}"])
        self.status.set_kind(kind_for("session", s.status))
        day = t[f"weekday.{dates.weekday_1_to_7(date.fromisoformat(s.date))}"]
        self.when.setText(t["attendance_view.when"].format(
            day=day, date=dates.display_date(s.date), start=s.start_time, end=s.end_time))
        teacher = s.teacher + (f" ({t['sessions_page.substitute_mark']})" if s.substitute else "")
        self.where.setText(t["attendance_view.where"].format(room=s.room, teacher=teacher))
        editable, notice = self._editable(s)
        self.notice.setText(notice)
        self.notice.setVisible(bool(notice))
        lines = attendance.roster(self._conn, self._ctx, self.session_id)
        self._fill(lines, editable)
        self.save.setVisible(editable)
        self.all_present.setVisible(editable)
        self._update_summary()

    def _editable(self, s) -> tuple[bool, str]:
        if not allowed(self._ctx, "attendance.save"):
            return False, ""
        if s.status == "cancelled":
            return False, t["attendance_view.cancelled"].format(reason=s.cancellation_reason)
        if s.date > dates.iso(dates.today()):
            return False, t["attendance.future"].format(date=dates.display_date(s.date))
        return True, ""

    def _fill(self, lines: list[RosterLine], editable: bool) -> None:
        with frozen_columns(self.table):
            self._fill_rows(lines, editable)
        self._fit_marks()
        self.table.setVisible(bool(lines))
        self.empty.setVisible(not lines)

    def _fill_rows(self, lines: list[RosterLine], editable: bool) -> None:
        self.table.setRowCount(0)
        self.table.setRowCount(len(lines))
        self._marks, self._saved = {}, {}
        for r, line in enumerate(lines):
            notes = []
            if line.trial:
                notes.append(t["attendance_view.trial"])
            if line.not_renewed:
                notes.append(t["attendance_view.not_renewed"])
            kind = "warning" if line.not_renewed else ("info" if line.trial else None)
            self.table.setItem(r, 0, item(line.student_name, item_id=line.enrollment_id))
            self.table.setItem(r, 1, item(line.student_number, mono=True))
            self.table.setItem(r, 2, item(" · ".join(notes), kind=kind if notes else None))
            marks = MarkButtons(line.status, editable)
            marks.changed.connect(self._update_summary)
            self.table.setCellWidget(r, 3, marks)
            self._marks[line.enrollment_id] = marks
            self._saved[line.enrollment_id] = line.status

    def _fit_marks(self) -> None:
        if self._marks:  # the buttons decide the column's width, not a cell text
            width = next(iter(self._marks.values())).sizeHint().width() + 24  # cell frame
            header = self.table.horizontalHeader()
            header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
            self.table.setColumnWidth(3, width)

    # ----- state -----

    def marks(self) -> dict[int, str]:
        """What is marked now (students left unmarked are not included)."""
        return {eid: m.status() for eid, m in self._marks.items() if m.status() is not None}

    def dirty(self) -> bool:
        return any(m.status() != self._saved[eid] for eid, m in self._marks.items())

    def _update_summary(self) -> None:
        current = [m.status() for m in self._marks.values()]
        summary = attendance.summarize(s for s in current if s is not None)
        self.summary.setText(t["attendance_view.summary"].format(
            present=summary.present, late=summary.late, absent=summary.absent,
            excused=summary.excused, unmarked=current.count(None)))
        self.save.setEnabled(self.dirty())

    # ----- actions -----

    def _all_present(self) -> None:
        for marks in self._marks.values():
            if marks.status() is None:
                marks.set_status("present")

    def _save(self) -> None:
        try:
            changed = attendance.save(self._conn, self._ctx, self.session_id, self.marks())
        except BusinessRuleError as exc:
            self.error.show_error(exc.message)
            return
        self.error.clear_error()
        self.refresh()
        toast(self, t["attendance_view.saved"].format(count=changed))

    def _print(self) -> None:
        """What is saved is printed: unsaved marks are not on the sheet."""
        try:
            path = printing.session_sheet(self._conn, self._ctx, self.session_id)
        except (BusinessRuleError, OSError) as exc:
            self.error.show_error(getattr(exc, "message", None) or t["print.failed"])
            return
        common.open_document(path)
        toast(self, t["print.done"].format(name=path.name))

    def _back(self) -> None:
        if self.dirty() and not confirm(self, t["attendance_view.leave_title"],
                                        t["attendance_view.leave"],
                                        t["attendance_view.leave_action"]):
            return
        self.back.emit()
