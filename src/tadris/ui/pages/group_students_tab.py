"""The group page's Élèves card: who is in the group now, the free seats, and « Inscrire un
élève »."""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from tadris.core.context import UserContext
from tadris.core.dates import display_date
from tadris.core.permissions import allowed
from tadris.domain.models import Enrollment, Group
from tadris.i18n.fr import t
from tadris.services import enrollments
from tadris.ui.enrollment_dialogs import AddStudentDialog
from tadris.ui.theme.status import kind_for
from tadris.ui.widgets.common import ask, primary_button, toast
from tadris.ui.widgets.forms import ListSection
from tadris.ui.widgets.tables import fit_columns, item


class GroupStudentsTab(QWidget):
    """The students in the group now. « Inscrire un élève » adds one; switching and leaving
    are done from the student's own page."""

    changed = Signal()  # a student was added: the page reloads its seats

    def __init__(self, conn, ctx: UserContext, group_id: int):
        super().__init__()
        self._conn = conn
        self._ctx = ctx
        self._group_id = group_id
        self._group: Group | None = None
        self.summary = QLabel()
        self.summary.setObjectName("sectionTitle")
        self.list = ListSection([t["group_students.col.name"], t["group_students.col.number"],
                                 t["group_students.col.status"], t["group_students.col.entry"],
                                 t["group_students.col.note"]],
                                t["group_students.empty"], sortable=True)
        self.list.toolbar.insertWidget(0, self.summary)
        self.add_student = self.list.add_button(primary_button(t["group_students.add"]),
                                                end=True)
        self.add_student.setDefault(False)
        self.add_student.clicked.connect(self._add)
        fit_columns(self.list.table, stretch=(0, 4))
        hint = QLabel(t["group_students.hint"])
        hint.setObjectName("caption")
        hint.setWordWrap(True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addWidget(self.list, 1)
        layout.addWidget(hint)

    def show_group(self, group: Group) -> None:
        """Called by the group page with its freshly loaded group."""
        self._group = group
        self.refresh()

    def refresh(self) -> None:
        if self._group is None:
            return
        live = [e for e in enrollments.for_group(self._conn, self._ctx, self._group_id)
                if e.is_live]
        g = self._group
        free = max(g.seats - len(live), 0)
        self.summary.setText(t["group_students.summary"].format(
            enrolled=len(live), seats=g.seats, free=free,
            trials=sum(e.status == "trial" for e in live)))
        self.add_student.setVisible(g.status != "closed"
                                    and allowed(self._ctx, "enrollment.create"))
        self.add_student.setEnabled(free > 0)
        self.add_student.setToolTip("" if free else t["group_students.full"])
        self.list.set_rows([self._cells(e) for e in live])

    def _add(self) -> None:
        if self._group is None:
            return
        dialog = AddStudentDialog(self._conn, self._ctx, self._group, parent=self)
        if ask(dialog):
            self.list.clear_error()
            self.changed.emit()  # the page reloads the group, then this list
            self.list.select_id(dialog.enrollment_id)
            toast(self, t["student_groups.enrolled"].format(name=dialog.chosen_name(),
                                                            group=self._group.title))

    @staticmethod
    def _cells(e: Enrollment) -> list:
        notes = []
        if e.other_level:
            notes.append(t["student_groups.note.other_level"].format(level=e.registration_level))
        if e.switched_from_id is not None:
            notes.append(t["group_students.note.switched_in"])
        if e.started_as_trial and e.status != "trial":
            notes.append(t["student_groups.note.after_trial"])
        return [
            item(e.student_name, e.student_name.casefold(), item_id=e.id),
            item(e.student_number, mono=True),
            item(t[f"enrollment_status.{e.status}"], e.status,
                 kind=kind_for("enrollment", e.status)),
            item(display_date(e.enrolled_on), e.enrolled_on),
            item(" · ".join(notes)),
        ]
