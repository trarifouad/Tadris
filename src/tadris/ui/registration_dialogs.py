"""Dialogs of the student's Inscription tab: register for the year, change the level, cancel."""

from PySide6.QtWidgets import QLineEdit

from tadris.core.context import UserContext
from tadris.core.errors import ValidationError
from tadris.core.money import format_dzd
from tadris.domain.models import Registration, SchoolYear, Student
from tadris.i18n.fr import t
from tadris.services import catalog, registrations
from tadris.ui.widgets.common import labeled
from tadris.ui.widgets.forms import FormDialog, caption, row
from tadris.ui.widgets.inputs import id_combo, money_edit, read_money


def level_combo(conn, ctx: UserContext, selected: int | None = None):
    """Active levels in their school order, with an empty first choice."""
    items = [(t["registration_dialog.choose_level"], None)]
    items += [(level.name, level.id)
              for level in catalog.list_items(conn, ctx, "level", active_only=True)]
    return id_combo(items, selected)


def required_level(combo) -> int:
    level_id = combo.currentData()
    if level_id is None:
        raise ValidationError(t["registration.level_required"])
    return level_id


class RegistrationDialog(FormDialog):
    """Register the student in the open year: level and fee (the default, or typed)."""

    def __init__(self, conn, ctx: UserContext, student: Student, year: SchoolYear, parent=None):
        super().__init__(t["registration_dialog.title"].format(label=year.label),
                         t["registration_dialog.submit"], parent=parent)
        self._conn, self._ctx, self._student = conn, ctx, student
        self.registration_id: int | None = None
        default = registrations.default_fee(conn)
        self.level = level_combo(conn, ctx)
        self.fee = money_edit(default)
        who = caption(t["registration_dialog.caption"].format(
            name=student.full_name, number=student.student_number))
        who.setWordWrap(True)
        self.add(who)
        self.add(row(labeled(t["registration_dialog.level"], self.level, required=True),
                     labeled(t["registration_dialog.fee"], self.fee)))
        note = caption(t["registration_dialog.fee_caption"].format(fee=format_dzd(default)))
        note.setWordWrap(True)
        self.add(note)
        self.finish(self.level)

    def save(self) -> None:
        self.registration_id = registrations.register(
            self._conn, self._ctx, self._student.id, required_level(self.level),
            read_money(self.fee, empty=0))


class ChangeLevelDialog(FormDialog):
    def __init__(self, conn, ctx: UserContext, registration: Registration, parent=None):
        super().__init__(t["change_level_dialog.title"], t["action.save"], parent=parent)
        self._conn, self._ctx, self._registration = conn, ctx, registration
        self.level = level_combo(conn, ctx, registration.level_id)
        self.add(labeled(t["registration_dialog.level"], self.level, required=True))
        note = caption(t["change_level_dialog.caption"].format(
            level=registration.level, label=registration.year_label))
        note.setWordWrap(True)
        self.add(note)
        self.finish(self.level)

    def save(self) -> None:
        registrations.change_level(self._conn, self._ctx, self._registration.id,
                                   required_level(self.level))


class CancelRegistrationDialog(FormDialog):
    """Director only: the reason goes to the audit log; the open fee charge is cancelled."""

    def __init__(self, conn, ctx: UserContext, registration: Registration, student: Student,
                 parent=None):
        super().__init__(t["cancel_registration_dialog.title"],
                         t["cancel_registration_dialog.submit"], parent=parent)
        self._conn, self._ctx, self._registration = conn, ctx, registration
        self.submit.setProperty("variant", "danger")
        self.reason = QLineEdit()
        self.reason.setPlaceholderText(t["cancel_registration_dialog.placeholder"])
        note = caption(t["cancel_registration_dialog.caption"].format(
            name=student.full_name, label=registration.year_label,
            fee=format_dzd(registration.fee_amount)))
        note.setWordWrap(True)
        self.add(note)
        self.add(labeled(t["cancel_registration_dialog.reason"], self.reason, required=True))
        self.finish(self.reason)

    def save(self) -> None:
        registrations.cancel(self._conn, self._ctx, self._registration.id, self.reason.text())
