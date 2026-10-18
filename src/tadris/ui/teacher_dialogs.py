from datetime import date

from PySide6.QtWidgets import QLineEdit

from tadris.core import dates
from tadris.core.context import UserContext
from tadris.core.dates import parse_display_date
from tadris.core.percent import format_percent
from tadris.core.phones import format_phone
from tadris.domain.models import Teacher, TeacherInput
from tadris.i18n.fr import t
from tadris.services import teachers
from tadris.ui.setup_dialogs import required_date
from tadris.ui.widgets.common import labeled
from tadris.ui.widgets.date_edit import DateLineEdit
from tadris.ui.widgets.forms import FormDialog, caption, row
from tadris.ui.widgets.inputs import percent_edit, read_percent


class TeacherDialog(FormDialog):
    """New teacher with a starting rate, or edit name, phone and arrival date."""

    def __init__(self, conn, ctx: UserContext, teacher: Teacher | None = None, parent=None):
        key = "teacher_dialog.new_title" if teacher is None else "teacher_dialog.edit_title"
        super().__init__(t[key], t["action.save"], width=640, parent=parent)
        self._conn, self._ctx, self._teacher = conn, ctx, teacher
        self.teacher_id: int | None = None if teacher is None else teacher.id
        self.full_name = QLineEdit()
        self.phone = QLineEdit()
        self.phone.setPlaceholderText("0661 90 25 47")
        self.hire_date = DateLineEdit(maximum=dates.today())
        self.rate = percent_edit()
        self.rate_from = DateLineEdit()
        if teacher is not None:
            self.full_name.setText(teacher.full_name)
            self.phone.setText(format_phone(teacher.phone))
            if teacher.hire_date:
                self.hire_date.set_value(date.fromisoformat(teacher.hire_date))
        else:
            self.rate_from.set_value(dates.today())
        self.add(labeled(t["teacher_dialog.name"], self.full_name, required=True))
        self.add(row(labeled(t["teacher_dialog.phone"], self.phone),
                     labeled(t["teacher_dialog.hire_date"], self.hire_date)))
        if teacher is None:
            self.add(row(labeled(t["teacher_dialog.rate"], self.rate, required=True),
                         labeled(t["teacher_dialog.rate_from"], self.rate_from, required=True)))
            note = caption(t["teacher_dialog.rate_caption"])
            note.setWordWrap(True)
            self.add(note)
        self.finish(self.full_name)

    def _data(self) -> TeacherInput:
        return TeacherInput(self.full_name.text(), self.phone.text(),
                            parse_display_date(self.hire_date.text()))

    def save(self) -> None:
        data = self._data()
        if self._teacher is None:
            self.teacher_id = teachers.create(self._conn, self._ctx, data,
                                              read_percent(self.rate),
                                              required_date(self.rate_from))
        else:
            teachers.update(self._conn, self._ctx, self._teacher.id, data)


class RateDialog(FormDialog):
    def __init__(self, conn, ctx: UserContext, teacher: Teacher, parent=None):
        super().__init__(t["rate_dialog.title"], t["action.save"], parent=parent)
        self._conn, self._ctx, self._teacher = conn, ctx, teacher
        self.rate = percent_edit()
        self.valid_from = DateLineEdit()
        self.valid_from.set_value(dates.today())
        self.add(row(labeled(t["rate_dialog.rate"], self.rate, required=True),
                     labeled(t["rate_dialog.from"], self.valid_from, required=True)))
        if teacher.current_rate_bp is not None:
            note = caption(t["rate_dialog.caption"].format(
                rate=format_percent(teacher.current_rate_bp)))
            note.setWordWrap(True)
            self.add(note)
        self.finish(self.rate)

    def save(self) -> None:
        teachers.set_rate(self._conn, self._ctx, self._teacher.id, read_percent(self.rate),
                          required_date(self.valid_from))
