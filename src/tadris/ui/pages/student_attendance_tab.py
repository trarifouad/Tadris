"""The student's Présences tab: every recorded attendance, latest first, with the counts."""

from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from tadris.core.context import UserContext
from tadris.core.dates import display_date
from tadris.i18n.fr import t
from tadris.services import attendance
from tadris.ui.theme.status import kind_for
from tadris.ui.widgets.forms import ListSection
from tadris.ui.widgets.tables import fit_columns, item


class StudentAttendanceTab(QWidget):
    def __init__(self, conn, ctx: UserContext, student_id: int):
        super().__init__()
        self._conn = conn
        self._ctx = ctx
        self._student_id = student_id
        self.summary = QLabel()
        self.summary.setObjectName("sectionTitle")
        self.list = ListSection([t["student_attendance.col.date"],
                                 t["student_attendance.col.time"],
                                 t["student_attendance.col.group"],
                                 t["student_attendance.col.status"]],
                                t["student_attendance.empty"])
        self.list.toolbar.insertWidget(0, self.summary)
        fit_columns(self.list.table, stretch=(2,))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 16, 0, 0)
        layout.addWidget(self.list)
        self.refresh()

    def refresh(self) -> None:
        history = attendance.for_student(self._conn, self._ctx, self._student_id)
        s = attendance.summarize(r.status for r in history)
        self.summary.setText(t["student_attendance.summary"].format(
            present=s.present, late=s.late, absent=s.absent, excused=s.excused))
        self.list.set_rows([[
            item(display_date(r.date), item_id=r.session_id),
            item(f"{r.start_time} – {r.end_time}", mono=True),
            item(r.group_title),
            item(t[f"attendance_status.{r.status}"], kind=kind_for("attendance", r.status)),
        ] for r in history])
