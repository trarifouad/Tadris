"""The student's Groupes tab: the groups the student is in, and those left or switched."""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QPushButton, QVBoxLayout, QWidget

from tadris.core.context import UserContext
from tadris.core.dates import display_date
from tadris.core.permissions import allowed
from tadris.domain.models import Enrollment
from tadris.i18n.fr import t
from tadris.services import enrollments, registrations, students
from tadris.ui.enrollment_dialogs import EnrollDialog, LeaveDialog, SwitchDialog
from tadris.ui.theme.status import kind_for
from tadris.ui.widgets.common import ask, primary_button, toast, variant_button
from tadris.ui.widgets.forms import ListSection
from tadris.ui.widgets.tables import fit_columns, item


class StudentGroupsTab(QWidget):
    changed = Signal()

    def __init__(self, conn, ctx: UserContext, student_id: int):
        super().__init__()
        self._conn = conn
        self._ctx = ctx
        self._student_id = student_id
        self._enrollments: dict[int, Enrollment] = {}
        can_update = allowed(ctx, "enrollment.update")

        self.list = ListSection([t["student_groups.col.group"], t["student_groups.col.status"],
                                 t["student_groups.col.entry"], t["student_groups.col.exit"],
                                 t["student_groups.col.note"]], "")
        self.enroll = self.list.add_button(primary_button(t["student_groups.enroll"]), end=True)
        self.enroll.setDefault(False)
        self.enroll.clicked.connect(self._enroll)
        self.confirm_trial = self.list.add_button(QPushButton(t["student_groups.confirm_trial"]))
        self.confirm_trial.clicked.connect(self._confirm_trial)
        self.switch = self.list.add_button(QPushButton(t["student_groups.switch"]))
        self.switch.clicked.connect(self._switch)
        self.leave = self.list.add_button(variant_button(t["student_groups.leave"], "danger"))
        self.leave.clicked.connect(self._leave)
        for button in (self.confirm_trial, self.switch, self.leave):
            button.setVisible(can_update)
        self.list.selection_changed.connect(self._update_buttons)
        fit_columns(self.list.table, stretch=(0, 4))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 16, 0, 0)
        layout.addWidget(self.list)
        self.refresh()

    def refresh(self) -> None:
        student = students.get(self._conn, self._ctx, self._student_id)
        registration = registrations.current(self._conn, self._ctx, self._student_id)
        listed = enrollments.for_student(self._conn, self._ctx, self._student_id)
        self._enrollments = {e.id: e for e in listed}
        if registration is None:
            self.list.empty.setText(t["student_groups.not_registered"])
        else:
            self.list.empty.setText(t["student_groups.empty"])
        self.enroll.setVisible(registration is not None and student.status == "active"
                               and allowed(self._ctx, "enrollment.create"))
        self.list.set_rows([self._cells(e) for e in listed])

    def _cells(self, e: Enrollment) -> list:
        notes = []
        if e.other_level:
            notes.append(t["student_groups.note.other_level"].format(level=e.registration_level))
        origin = self._enrollments.get(e.switched_from_id)
        if origin is not None:
            notes.append(t["student_groups.note.from"].format(group=origin.group_name))
        if e.started_as_trial and e.status != "trial":
            notes.append(t["student_groups.note.after_trial"])
        return [
            item(e.group_title, item_id=e.id),
            item(t[f"enrollment_status.{e.status}"], kind=kind_for("enrollment", e.status)),
            item(display_date(e.enrolled_on)),
            item(display_date(e.left_on) if e.left_on else ""),
            item(" · ".join(notes)),
        ]

    def selected(self) -> Enrollment | None:
        enrollment_id = self.list.selected_id()
        return None if enrollment_id is None else self._enrollments.get(enrollment_id)

    def _update_buttons(self) -> None:
        e = self.selected()
        live = e is not None and e.is_live
        self.confirm_trial.setEnabled(e is not None and e.status == "trial")
        self.switch.setEnabled(live)
        self.leave.setEnabled(live)

    def _done(self, message: str, select: int | None = None) -> None:
        self.list.clear_error()
        self.refresh()
        if select is not None:
            self.list.select_id(select)
        self.changed.emit()
        toast(self, message)

    def _enroll(self) -> None:
        student = students.get(self._conn, self._ctx, self._student_id)
        dialog = EnrollDialog(self._conn, self._ctx, student, parent=self)
        if ask(dialog):
            self._done(t["student_groups.enrolled"].format(name=student.full_name,
                                                           group=dialog.chosen_title()),
                       dialog.enrollment_id)

    def _confirm_trial(self) -> None:
        e = self.selected()
        if e is None:
            return
        if self.list.run(enrollments.confirm_trial, self._conn, self._ctx, e.id):
            self._done(t["student_groups.trial_confirmed"].format(group=e.group_title), e.id)

    def _switch(self) -> None:
        e = self.selected()
        if e is None:
            return
        dialog = SwitchDialog(self._conn, self._ctx, e, parent=self)
        if ask(dialog):
            self._done(t["student_groups.switched"].format(old=e.group_title,
                                                           new=dialog.chosen_title()),
                       dialog.new_id)

    def _leave(self) -> None:
        e = self.selected()
        if e is None:
            return
        if ask(LeaveDialog(self._conn, self._ctx, e, parent=self)):
            self._done(t["student_groups.left"].format(group=e.group_title), e.id)
