"""Dialogs of the student's Groupes tab: enroll in a group, switch group, leave a group; and
of the group's page: add a student to the group."""

from PySide6.QtWidgets import QCheckBox, QLineEdit, QVBoxLayout, QWidget

from tadris.core import dates
from tadris.core.context import UserContext
from tadris.core.errors import ValidationError
from tadris.core.money import format_dzd
from tadris.core.permissions import allowed
from tadris.core.text import fold
from tadris.domain.models import (
    Enrollment,
    Group,
    GroupCandidate,
    GroupOption,
    Student,
    Subscription,
)
from tadris.i18n.fr import t
from tadris.services import enrollments, subscriptions
from tadris.ui.payment_dialogs import debt_banner
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


def months_after_note(conn, ctx: UserContext, enrollment: Enrollment,
                      last_day) -> str:
    """What leaving the group on `last_day` does to its months to come: cancelled, or kept
    when money was paid on them (even if refunded since) or a teacher was paid for them."""
    if last_day is None or enrollment.status != "active":
        return ""
    if enrollment.enrolled_on > dates.iso(dates.today()):
        last_day = dates.today()  # the seat is freed now; the last day is still the entry day
    months = subscriptions.after(conn, ctx, enrollment.id, last_day)

    def kept(m: Subscription) -> str:
        why = (t["leave.kept_paid"].format(amount=format_dzd(m.paid)) if m.paid
               else t["leave.kept_payout"])
        return f"{dates.short_period(m.start_date, m.end_date)} ({why})"

    parts = []
    cancelled = [f"{dates.short_period(m.start_date, m.end_date)} ({format_dzd(m.price)})"
                 for m in months if m.cancelled_on_leaving]
    if cancelled:
        parts.append(t["leave.months_cancelled"].format(months=", ".join(cancelled)))
    held = [kept(m) for m in months if not m.cancelled_on_leaving]
    if held:
        parts.append(t["leave.months_kept"].format(months=", ".join(held)))
    return " ".join(parts)


def offered(conn, ctx: UserContext, student_id: int,
            exclude_group: int | None = None) -> tuple[list[GroupOption], int]:
    """The groups the user may pick for the student (their level, and the open levels such as
    « Tous niveaux »), and how many full
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
        banner = debt_banner(conn, ctx, student_id)  # a new month will add to the debt
        if banner is not None:
            self.add(banner)
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
        self.months_note = caption()
        self.months_note.setWordWrap(True)
        self.add(self.months_note)
        self.date.textChanged.connect(lambda _text: self._months())
        self._months()
        self._add_reason()
        self.finish(self.picker.table)

    def _months(self) -> None:
        note = months_after_note(self._conn, self._ctx, self._enrollment, self.date.value())
        self.months_note.setText(note)
        self.months_note.setVisible(bool(note))

    def save(self) -> None:
        self.new_id = enrollments.switch(self._conn, self._ctx, self._enrollment.id,
                                         self._group_id(), required_date(self.date),
                                         self._reason())

    def chosen_title(self) -> str:
        option = self.picker.selected()
        return "" if option is None else option.group.title


class AddStudentDialog(FormDialog):
    """From the group's page: pick one of the students who may join it (searched by name or
    number), the entry date, the free trial. A student already in another group of its
    subject is offered to the director only, with a reason (the override)."""

    def __init__(self, conn, ctx: UserContext, group: Group, parent=None):
        super().__init__(t["add_student.title"], t["enroll_dialog.submit"], width=640,
                         parent=parent)
        self._conn, self._ctx, self._group = conn, ctx, group
        self.enrollment_id: int | None = None
        can_override = allowed(ctx, "enrollment.override")
        self._candidates = {c.student_id: c
                            for c in enrollments.candidates(conn, ctx, group.id)
                            if can_override or not c.same_subject}
        self.search = QLineEdit()
        self.search.setPlaceholderText(t["add_student.search"])
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(lambda _text: self._find())
        self.table = ruled_table([t["students.col.number"], t["add_student.col.student"],
                                  t["add_student.col.level"], t["enroll_dialog.col.note"]])
        header = self.table.horizontalHeader().height() or ROW_HEIGHT
        self.table.setFixedHeight(header + ROW_HEIGHT * VISIBLE_ROWS + 2)
        self.table.itemSelectionChanged.connect(self._picked)
        self.found = caption()
        self.found.setWordWrap(True)
        self.date = DateLineEdit()
        self.date.set_value(enrollments.default_date(group.start_date))
        self.trial = QCheckBox(t["enroll_dialog.trial"])
        self.trial_used = caption(t["enroll_dialog.trial_used"])
        self.reason = QLineEdit()
        self.reason.setPlaceholderText(t["enroll_dialog.reason_placeholder"])
        self.reason_box = labeled(t["enroll_dialog.reason"], self.reason, required=True)

        intro = caption(t["add_student.caption"].format(group=group.title))
        intro.setWordWrap(True)
        self.add(intro)
        if self._candidates:
            self.add(self.search)
            self.add(self.table)
            self.add(self.found)
            self.add(row(labeled(t["enroll_dialog.date"], self.date, required=True),
                         self.trial))
            self.add(self.trial_used)
            self.add(self.reason_box)
            self.trial_used.hide()
            self.reason_box.hide()
            self._find()
        else:
            for widget in (self.search, self.table, self.found):
                widget.hide()
            empty = caption(t["add_student.none_open" if group.level_open
                              else "add_student.none"].format(level=group.level))
            empty.setWordWrap(True)
            self.add(empty)
            self.submit.setEnabled(False)
        self.finish(self.search)

    def _find(self) -> None:
        query = fold(self.search.text().strip()) or ""
        shown = [c for c in self._candidates.values()
                 if query in fold(c.student_name) or query in c.student_number]
        fill(self.table, [self._cells(c) for c in shown])
        fit_columns(self.table, stretch=(1,))
        if shown:
            self.table.selectRow(0)
        who = (t["add_student.who_open"] if self._group.level_open
               else t["add_student.who"].format(level=self._group.level))
        self.found.setText(who if shown else t["picker.none_found"].format(
            query=self.search.text().strip()))
        self._picked()

    @staticmethod
    def _cells(c: GroupCandidate) -> list:
        note = item(t["enroll_dialog.same_subject"], kind="warning") if c.same_subject \
            else item("")
        return [item(c.student_number, item_id=c.student_id, mono=True), item(c.student_name),
                item(c.level), note]

    def selected(self) -> GroupCandidate | None:
        student_id = selected_id(self.table)
        return None if student_id is None else self._candidates.get(student_id)

    def _picked(self) -> None:
        c = self.selected()
        self.submit.setEnabled(c is not None)
        can_trial = c is not None and c.can_trial
        self.trial.setEnabled(can_trial)
        if not can_trial:
            self.trial.setChecked(False)
        self.trial_used.setVisible(c is not None and not c.can_trial)
        self.reason_box.setVisible(c is not None and c.same_subject)
        fit_to_content(self)

    def save(self) -> None:
        c = self.selected()
        if c is None:
            raise ValidationError(t["picker.choose"])
        self.enrollment_id = enrollments.enroll(
            self._conn, self._ctx, c.student_id, self._group.id,
            trial=self.trial.isChecked(), enrolled_on=required_date(self.date),
            override_reason=self.reason.text() if c.same_subject else None)

    def chosen_name(self) -> str:
        c = self.selected()
        return "" if c is None else c.student_name


class LeaveDialog(FormDialog):
    def __init__(self, conn, ctx: UserContext, enrollment: Enrollment, parent=None):
        super().__init__(t["leave_dialog.title"], t["leave_dialog.submit"], parent=parent)
        self._conn, self._ctx, self._enrollment = conn, ctx, enrollment
        self.submit.setProperty("variant", "danger")
        self._not_started = enrollment.enrolled_on > dates.iso(dates.today())
        self.date = DateLineEdit(maximum=dates.today())
        self.date.set_value(dates.today())
        self.reason = QLineEdit()
        self.reason.setPlaceholderText(t["leave_dialog.reason_placeholder"])
        caption_key = "leave_dialog.not_started" if self._not_started else "leave_dialog.caption"
        note = caption(t[caption_key].format(name=enrollment.student_name,
                                             group=enrollment.group_title,
                                             date=dates.display_date(enrollment.enrolled_on)))
        note.setWordWrap(True)
        self.add(note)
        if self._not_started:
            self.add(labeled(t["leave_dialog.reason"], self.reason))
        else:
            self.add(row(labeled(t["leave_dialog.date"], self.date, required=True),
                         labeled(t["leave_dialog.reason"], self.reason)))
            self.date.textChanged.connect(lambda _text: self._months())
        self.months_note = caption()
        self.months_note.setWordWrap(True)
        self.add(self.months_note)
        self._months()
        self.finish(self.reason if self._not_started else self.date)

    def _months(self) -> None:
        last = dates.today() if self._not_started else self.date.value()
        note = months_after_note(self._conn, self._ctx, self._enrollment, last)
        self.months_note.setText(note)
        self.months_note.setVisible(bool(note))

    def save(self) -> None:
        on = None if self._not_started else required_date(self.date)
        enrollments.leave(self._conn, self._ctx, self._enrollment.id, on, self.reason.text())
