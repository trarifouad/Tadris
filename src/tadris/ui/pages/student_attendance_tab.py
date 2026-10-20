"""The student's Présences tab: the counts over the whole history, then the recorded
attendance, latest first, a page at a time."""

from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from tadris.core.context import UserContext
from tadris.core.dates import display_date
from tadris.i18n.fr import t
from tadris.services import attendance
from tadris.ui.theme.status import kind_for
from tadris.ui.widgets.forms import ListSection
from tadris.ui.widgets.tables import PAGE_SIZE, MoreOnScroll, fit_columns, frozen_columns, item


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
        self._shown = self._total = 0
        self.pager = MoreOnScroll(self.list.table, self._load_more)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 16, 0, 0)
        layout.addWidget(self.list)
        self.refresh()

    def refresh(self) -> None:
        """The counts over the whole history; the latest page of marks, the older ones as
        the list is scrolled."""
        s = attendance.summary_for_student(self._conn, self._ctx, self._student_id)
        self.summary.setText(t["student_attendance.summary"].format(
            present=s.present, late=s.late, absent=s.absent, excused=s.excused))
        self._total = s.total
        page = attendance.for_student(self._conn, self._ctx, self._student_id,
                                      limit=PAGE_SIZE)
        self._shown = len(page)
        self.list.set_rows([self._cells(r) for r in page])
        self.pager.reset(self._shown < self._total)

    @staticmethod
    def _cells(r) -> list:
        return [
            item(display_date(r.date), item_id=r.session_id),
            item(f"{r.start_time} – {r.end_time}", mono=True),
            item(r.group_title),
            item(t[f"attendance_status.{r.status}"], kind=kind_for("attendance", r.status)),
        ]

    def _load_more(self) -> bool:
        page = attendance.for_student(self._conn, self._ctx, self._student_id,
                                      limit=PAGE_SIZE, offset=self._shown)
        table = self.list.table
        start = table.rowCount()
        with frozen_columns(table):
            table.setRowCount(start + len(page))
            for r, record in enumerate(page, start):
                for c, cell in enumerate(self._cells(record)):
                    table.setItem(r, c, cell)
        self._shown += len(page)
        return bool(page) and self._shown < self._total
