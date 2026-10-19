"""Dialogs of the student's Groupes tab: enroll in a group, switch group, leave a group."""

from PySide6.QtWidgets import QCheckBox, QLineEdit, QVBoxLayout, QWidget

from tadris.core import dates
from tadris.core.context import UserContext
from tadris.core.errors import ValidationError
from tadris.core.permissions import allowed
from tadris.domain.models import Enrollment, GroupOption, Student
from tadris.i18n.fr import t
from tadris.services import enrollments
from tadris.ui.setup_dialogs import required_date
from tadris.ui.widgets.common import fit_to_content, labeled
from tadris.ui.widgets.date_edit import DateLineEdit
from tadris.ui.widgets.forms import FormDialog, caption, row
from tadris.ui.widgets.tables import (
    CENTER,
    ID_ROLE,
    ROW_HEIGHT,
    fill,
    fit_columns,
    item,
    ruled_table,
    selected_id,
)

VISIBLE_ROWS = 6


def offered(conn, ctx: UserContext, student_id: int,
            exclude_group: int | None = None) -> tuple[list[GroupOption], int]:
    """The groups the user may pick for the student (their level only), and how many full
    ones were left out. A group of a subject the student already has is offered to the
    director only (it needs the override). exclude_group: the group a switch leaves."""
    can_override = allowed(ctx, "enrollment.override")
    picked, full = [], 0
    for option in enrollments.options(conn, ctx, student_id, leaving_group_id=exclude_group):
        if option.already_in or option.group.id == exclude_group:
            continue
        if option.needs_override and not can_override:
            continue
        if option.free == 0:
            full += 1
            continue
        picked.append(option)
    return picked, full


class GroupPicker(QWidget):
    """A short table of groups to choose from: name, teacher, free seats, level note."""

    def __init__(self, options: list[GroupOption], on_change):
        super().__init__()
        self.options = {o.group.id: o for o in options}
        self.table = ruled_table([t["enroll_dialog.col.group"], t["enroll_dialog.col.teacher"],
                                  t["enroll_dialog.col.free"], t["enroll_dialog.col.note"]])
        fill(self.table, [self._cells(o) for o in options])
        fit_columns(self.table)
        header = self.table.horizontalHeader().height() or ROW_HEIGHT
        self.table.setFixedHeight(header + ROW_HEIGHT * max(min(len(options), VISIBLE_ROWS), 1)
                                  + 2)
        self.table.itemSelectionChanged.connect(on_change)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.table)

    @staticmethod
    def _cells(o: GroupOption) -> list:
        if o.same_subject:
            note = item(t["enroll_dialog.same_subject"], kind="warning")
        else:
            note = item("")
        return [
            item(o.group.title, item_id=o.group.id),
            item(o.group.teacher or "—"),
            item(f"{o.free} / {o.group.seats}", align=CENTER, mono=True),
            note,
        ]

    def selected(self) -> GroupOption | None:
        group_id = selected_id(self.table)
        return None if group_id is None else self.options.get(group_id)

    def select(self, group_id: int) -> None:
        for r in range(self.table.rowCount()):
            if self.table.item(r, 0).data(ID_ROLE) == group_id:
                self.table.selectRow(r)



class _PickGroupDialog(FormDialog):
    """Shared by enroll and switch: the group table, the date, and the override reason that
    shows when a group of another level is picked."""

    def __init__(self, conn, ctx: UserContext, title: str, submit: str, student_id: int,
                 exclude_group: int | None, intro: str, parent=None):
        super().__init__(title, submit, width=720, parent=parent)
        self._conn, self._ctx = conn, ctx
        options, full = offered(conn, ctx, student_id, exclude_group)
        self.picker = GroupPicker(options, self._picked)
        self.empty = caption(t["enroll_dialog.none"])
        self.empty.setWordWrap(True)
        self.full_note = caption(t["enroll_dialog.full_hidden"].format(count=full))
        self.date = DateLineEdit()
        self.reason = QLineEdit()
        self.reason.setPlaceholderText(t["enroll_dialog.reason_placeholder"])
        self.reason_box = labeled(t["enroll_dialog.reason"], self.reason, required=True)
        note = caption(intro)
        note.setWordWrap(True)
        self.add(note)
        self.add(self.picker if options else self.empty)
        self.picker.setVisible(bool(options))
        if full:
            self.add(self.full_note)
        self.submit.setEnabled(bool(options))

    def _add_reason(self) -> None:
        self.add(self.reason_box)
        self.reason_box.hide()

    def _picked(self) -> None:
        option = self.picker.selected()
        self.reason_box.setVisible(option is not None and option.needs_override)
        fit_to_content(self)

    def _group_id(self) -> int:
        option = self.picker.selected()
        if option is None:
            raise ValidationError(t["enroll_dialog.group_required"])
        return option.group.id

    def _reason(self) -> str | None:
        option = self.picker.selected()
        return None if option is None or not option.needs_override else self.reason.text()


class EnrollDialog(_PickGroupDialog):
    def __init__(self, conn, ctx: UserContext, student: Student, parent=None):
        super().__init__(conn, ctx, t["enroll_dialog.title"], t["enroll_dialog.submit"],
                         student.id, None,
                         t["enroll_dialog.caption"].format(name=student.full_name), parent)
        self._student = student
        self.enrollment_id: int | None = None
        self.trial = QCheckBox(t["enroll_dialog.trial"])
        can_trial = enrollments.can_take_trial(conn, student.id)
        self.trial.setEnabled(can_trial)
        self.date.set_value(dates.today())
        self.add(row(labeled(t["enroll_dialog.date"], self.date, required=True), self.trial))
        if not can_trial:
            self.add(caption(t["enroll_dialog.trial_used"]))
        self._add_reason()
        self.finish(self.picker.table)

    def _picked(self) -> None:
        option = self.picker.selected()
        if option is not None:  # today, or the group's first day if it has not started
            self.date.set_value(enrollments.default_date(option.group.start_date))
        super()._picked()

    def save(self) -> None:
        self.enrollment_id = enrollments.enroll(
            self._conn, self._ctx, self._student.id, self._group_id(),
            trial=self.trial.isChecked(), enrolled_on=required_date(self.date),
            override_reason=self._reason())

    def chosen_title(self) -> str:
        option = self.picker.selected()
        return "" if option is None else option.group.title


class SwitchDialog(_PickGroupDialog):
    def __init__(self, conn, ctx: UserContext, enrollment: Enrollment, parent=None):
        super().__init__(conn, ctx, t["switch_dialog.title"], t["switch_dialog.submit"],
                         enrollment.student_id, enrollment.group_id,
                         t["switch_dialog.caption"].format(group=enrollment.group_title),
                         parent)
        self._enrollment = enrollment
        self.new_id: int | None = None
        self.date.maximum = dates.today()
        self.date.set_value(dates.today())
        self.add(row(labeled(t["switch_dialog.date"], self.date, required=True), QWidget()))
        self._add_reason()
        self.finish(self.picker.table)

    def save(self) -> None:
        self.new_id = enrollments.switch(self._conn, self._ctx, self._enrollment.id,
                                         self._group_id(), required_date(self.date),
                                         self._reason())

    def chosen_title(self) -> str:
        option = self.picker.selected()
        return "" if option is None else option.group.title


class LeaveDialog(FormDialog):
    def __init__(self, conn, ctx: UserContext, enrollment: Enrollment, parent=None):
        super().__init__(t["leave_dialog.title"], t["leave_dialog.submit"], parent=parent)
        self._conn, self._ctx, self._enrollment = conn, ctx, enrollment
        self.submit.setProperty("variant", "danger")
        self.date = DateLineEdit(maximum=dates.today())
        self.date.set_value(dates.today())
        self.reason = QLineEdit()
        self.reason.setPlaceholderText(t["leave_dialog.reason_placeholder"])
        note = caption(t["leave_dialog.caption"].format(name=enrollment.student_name,
                                                        group=enrollment.group_title))
        note.setWordWrap(True)
        self.add(note)
        self.add(row(labeled(t["leave_dialog.date"], self.date, required=True),
                     labeled(t["leave_dialog.reason"], self.reason)))
        self.finish(self.date)

    def save(self) -> None:
        enrollments.leave(self._conn, self._ctx, self._enrollment.id, required_date(self.date),
                          self.reason.text())
