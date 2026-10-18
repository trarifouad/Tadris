from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from tadris.core.context import UserContext
from tadris.core.dates import display_date
from tadris.core.permissions import allowed
from tadris.core.phones import format_phone
from tadris.core.text import fold
from tadris.domain.models import StudentListItem
from tadris.i18n.fr import t
from tadris.services import students
from tadris.ui.pages.student_detail import StudentDetailView
from tadris.ui.student_dialog import StudentDialog
from tadris.ui.theme.status import kind_for
from tadris.ui.widgets.common import ask, primary_button, toast
from tadris.ui.widgets.forms import ListDetailPage
from tadris.ui.widgets.tables import CENTER, ID_ROLE, fill, item, ruled_table

SEARCH_DELAY_MS = 250
STATUS_FILTERS = (("students.filter.active", "active"),
                  ("students.filter.inactive", "inactive"),
                  ("students.filter.all", None))


class StudentsPage(ListDetailPage):
    """Élèves: the list, and a student's detail page in place of it."""

    def __init__(self, conn, ctx: UserContext):
        super().__init__(StudentListView(conn, ctx),
                         lambda student_id: StudentDetailView(conn, ctx, student_id))

    def open_student(self, student_id: int) -> None:
        self.open(student_id)

    def refresh(self) -> None:
        super().refresh()
        if self.detail is not None:
            self.detail.contacts.refresh()  # contacts are shared with siblings


class StudentListView(QWidget):
    opened = Signal(int)

    def __init__(self, conn, ctx: UserContext):
        super().__init__()
        self._conn = conn
        self._ctx = ctx
        self.setObjectName("page")

        heading = QLabel(t["nav.students"])
        heading.setObjectName("pageTitle")
        self.new_student = primary_button(t["students.new"])
        self.new_student.setDefault(False)
        self.new_student.clicked.connect(self._create)
        self.new_student.setVisible(allowed(ctx, "student.create"))
        head = QHBoxLayout()
        head.addWidget(heading)
        head.addStretch()
        head.addWidget(self.new_student)

        self.search = QLineEdit()
        self.search.setPlaceholderText(t["students.search"])
        self.search.setClearButtonEnabled(True)
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(SEARCH_DELAY_MS)
        self._debounce.timeout.connect(self.refresh)
        self.search.textChanged.connect(self._debounce.start)
        self.search.returnPressed.connect(self.refresh)
        self.status = QComboBox()
        for label_key, value in STATUS_FILTERS:
            self.status.addItem(t[label_key], value)
        self.status.currentIndexChanged.connect(self.refresh)
        filters = QHBoxLayout()
        filters.setSpacing(12)
        filters.addWidget(self.search, 3)
        filters.addWidget(self.status, 1)
        filters.addStretch(2)

        self.table = ruled_table([
            t["students.col.number"],
            t["students.col.last_name"],
            t["students.col.first_name"],
            t["students.col.birth_date"],
            t["students.col.contact"],
            t["students.col.phone"],
            t["students.col.status"],
        ], sortable=True)
        self.table.setSortingEnabled(True)
        self.table.sortByColumn(1, Qt.SortOrder.AscendingOrder)
        self.table.activated.connect(self._open_row)
        self.empty = QLabel()
        self.empty.setObjectName("emptyState")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty.setWordWrap(True)
        self.count = QLabel()
        self.count.setObjectName("caption")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 24)
        layout.setSpacing(16)
        layout.addLayout(head)
        layout.addLayout(filters)
        layout.addWidget(self.table, 1)
        layout.addWidget(self.empty)
        layout.addStretch(0)
        layout.addWidget(self.count)
        self.refresh()

    def refresh(self) -> None:
        self._debounce.stop()
        found = students.search(self._conn, self._ctx, self.search.text(),
                                self.status.currentData())
        fill(self.table, [self._cells(s) for s in found])
        filtered = bool(self.search.text().strip()) or self.status.currentIndex() != 0
        self.empty.setText(t["students.no_match" if filtered else "students.empty"])
        self.empty.setVisible(not found)
        self.table.setVisible(bool(found))
        self.count.setText(t["students.count"].format(count=len(found)))

    @staticmethod
    def _cells(s: StudentListItem) -> list:
        return [
            item(s.student_number, s.student_number, mono=True, item_id=s.id),
            item(s.last_name, (fold(s.last_name), fold(s.first_name))),
            item(s.first_name, (fold(s.first_name), fold(s.last_name))),
            item(display_date(s.birth_date) if s.birth_date else "", s.birth_date or "",
                 align=CENTER),
            item(s.main_contact or "", fold(s.main_contact or "")),
            item(format_phone(s.main_phone), s.main_phone or "", mono=True),
            item(t[f"student_status.{s.status}"], s.status, kind=kind_for("student", s.status)),
        ]

    def student_ids(self) -> list[int]:
        """Row order as displayed."""
        return [self.table.item(r, 0).data(ID_ROLE) for r in range(self.table.rowCount())]

    def _open_row(self, index) -> None:
        self.opened.emit(self.table.item(index.row(), 0).data(ID_ROLE))

    def _create(self) -> None:
        dialog = StudentDialog(self._conn, self._ctx, parent=self)
        if not ask(dialog):
            return
        student = students.get(self._conn, self._ctx, dialog.student_id)
        toast(self, t["students.created"].format(name=student.full_name,
                                                 number=student.student_number))
        self.refresh()
        self.opened.emit(student.id)
